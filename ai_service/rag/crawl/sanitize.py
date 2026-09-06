"""
入口注入防护 sanitize（module-086）— 爬虫内容确定性规则清洗 + canary 金丝雀
===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== =====

三态处置（crawl_sanitize_mode，plan 裁定 2）：
  detect —— 只扫不改（内容零改动，评估/逃生口）
  strip  —— 默认档：载体族（HTML 注释 / script/style 块 / 零宽字符）直接剥离 +
           指令族（忽略指令 / 数据外传 / 破坏性工具 / CSS 隐藏文本）只记
           findings 不改内容（防误伤代码围栏内教学文本）
  strict —— strip 全部 + 任一指令族命中 → rejected=True（爬虫侧强制
           review_status="rejected"，对齐 module-075 rejected 仍入库契约）

代码围栏（```...```）内的教学文本不参与指令族扫描（裁定 2"防误伤"动机 +
AC-21 构成性保证；载体族仍无条件剥离——脚本标签被剥属预期，用例集良性②）。

canary 金丝雀（裁定 3）：每篇爬虫文档唯一 8-hex 令牌，按 ~250 字符间隔在行
边界重复插入（纯 ASCII 对 NFKC/清洗/分块稳定，重复插入保证父块几乎必含）；
映射行落 crawl_canaries 表；输出侧 check_canary_leak 对 chat 两主路径做泄漏
检测（命中 → warning + canary_leak span，kind=security/status=blocked，走
module-088 既有通道零 schema 改动）。

本模块纯 stdlib/re 零新依赖；DB 原语全异常 fail-open（不阻断入库/回答主链路）；
正则全线性模式（单层 .*? + DOTALL），禁嵌套量词防回溯爆炸。
"""
import logging
import re
import uuid
from dataclasses import dataclass, field

from sqlalchemy import text as sql_text

from src import tracing
from src.config import settings

logger = logging.getLogger(__name__)


@dataclass
class SanitizeResult:
    """单页 sanitize 结果（findings 项：{category, action, count, sample}，仅含命中类目）"""
    cleaned_text: str
    findings: list = field(default_factory=list)
    rejected: bool = False


# --- 载体族（strip 档直接剥离；对可见正文零损伤——注释/脚本/不可见字符本非正文） ---
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_HIDDEN_UNICODE_RE = re.compile(r"[\u00ad\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]")

# --- 指令族（只标记不改动；hidden_text 字面命中，良性用例③ strict FP 属已知语义） ---
_HIDDEN_TEXT_RE = re.compile(
    r"display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0(px|em)?",
    re.IGNORECASE)

_PATTERN_GROUPS: dict = {
    "html_comment": [_HTML_COMMENT_RE],
    "script_style": [_SCRIPT_STYLE_RE],
    "hidden_unicode": [_HIDDEN_UNICODE_RE],
    "instruction_override": [
        re.compile(p, re.IGNORECASE) for p in (
            r"ignore\s+(all\s+)?(previous|prior|above|earlier)",
            r"(忽略|无视)\s*(之前|以上|上面|先前|前面)的(所有)?(指令|提示|设定|内容)",
            r"disregard\s+(all\s+)?(previous|prior|above)",
            r"(system\s*prompt|系统提示(词)?)\s*[:：]",
            r"你(现在|从现在起)是(新|真|真正的)?(系统|管理员|开发者)",
            r"<\|?(im_start|system)\|?>",
        )
    ],
    "exfiltration": [
        re.compile(p, re.IGNORECASE) for p in (
            r"(把|将)?(以下|上述|以上|这些|本页|本文)(内容|数据|信息|文本)(发送|上传|外传|提交)(到|至|给)",
            r"(send|post|upload|forward|exfiltrate)\s+(this|the|all)?\s*(data|content|text|information)\s+(to|via)\s+\S*(http|api|webhook)",
        )
    ],
    "destructive_tool": [
        re.compile(p, re.IGNORECASE) for p in (
            r"(删除|清空|销毁)(所有|全部|all)",
            r"(delete|drop|truncate|wipe)\s+(all|every)\s+(documents|records|data|rows)",
            r"(调用|执行|run|execute)\s*(删除|delete|drop)",
        )
    ],
    "hidden_text": [_HIDDEN_TEXT_RE],
}

_CARRIER_CATEGORIES = ("html_comment", "script_style", "hidden_unicode")
_INJECTION_CATEGORIES = tuple(k for k in _PATTERN_GROUPS if k not in _CARRIER_CATEGORIES)
_FENCE_RE = re.compile(r"```.*?(?:```|\Z)", re.DOTALL)

# --- canary 金丝雀（行为契约：令牌 [canary:{8位小写hex}]，检测正则锁定） ---
_CANARY_INTERVAL_CHARS = 250
_CANARY_TOKEN_RE = re.compile(r"canary:([0-9a-f]{8})")
_SAMPLE_MAX = 80


def _scan_category(content: str, patterns: list) -> tuple:
    """扫描单类目：返回（命中次数, 首个样例截 80 字符防日志撑爆）"""
    count, sample = 0, ""
    for pat in patterns:
        for m in pat.finditer(content):
            count += 1
            if not sample:
                sample = m.group(0)[:_SAMPLE_MAX]
    return count, sample


def _scan_groups(content: str, categories: tuple, action: str) -> list:
    """按类目组扫描并聚合成 findings 列表（仅记录命中类目）"""
    findings = []
    for cat in categories:
        count, sample = _scan_category(content, _PATTERN_GROUPS[cat])
        if count:
            findings.append({"category": cat, "action": action,
                             "count": count, "sample": sample})
    return findings


def sanitize_crawl_content(content: str, mode: str) -> SanitizeResult:
    """三态入口（裁定 2）：detect 只扫不改 / strip 载体剥离+指令标记 / strict 加拒收

    载体族计数取自原文（剥离对象），指令族扫描在载体剥离后、代码围栏掩码后
    的文本上进行（残留风险口径）。findings 仅含命中类目，样例截 80 字符。

    Args:
        content: 抓取页面原始文本（HTML 形态，尚未进 document_cleaner 清洗层）
        mode: detect / strip / strict（settings.crawl_sanitize_mode）

    Returns:
        SanitizeResult（cleaned_text / findings / rejected）
    """
    if mode == "detect":
        masked = _FENCE_RE.sub("", content)
        return SanitizeResult(content, _scan_groups(content, _CARRIER_CATEGORIES, "detect")
                              + _scan_groups(masked, _INJECTION_CATEGORIES, "detect"), False)
    cleaned = _HIDDEN_UNICODE_RE.sub("", content)
    cleaned = _SCRIPT_STYLE_RE.sub("", cleaned)
    cleaned = _HTML_COMMENT_RE.sub("", cleaned)
    carrier_findings = _scan_groups(content, _CARRIER_CATEGORIES, "strip")
    masked = _FENCE_RE.sub("", cleaned)
    instruction_findings = _scan_groups(masked, _INJECTION_CATEGORIES, "mark")
    rejected = mode == "strict" and bool(instruction_findings)
    return SanitizeResult(cleaned, carrier_findings + instruction_findings, rejected)


def new_canary() -> str:
    """生成 8 位小写 hex canary 令牌（uuid4 截取，单文档唯一）"""
    return uuid.uuid4().hex[:8]


def embed_canary(content: str, canary: str) -> str:
    """按 ~250 字符间隔在行边界插入 [canary:xxx]（短文/无行边界文末补插）

    行累积越过 _CANARY_INTERVAL_CHARS 即在当前行边界插入令牌并重新计数；
    全文未触发插入（短文）时末尾补 1 个，保证每篇文档至少携带 1 个令牌。

    Args:
        content: 清洗后待入库文本
        canary: 8 位 hex 令牌（new_canary() 产出）

    Returns:
        插入令牌后的文本（正文零截断零改动，仅追加令牌）
    """
    token = f"[canary:{canary}]"
    out: list = []
    acc = 0
    inserted = False
    for line in content.split("\n"):
        out.append(line)
        acc += len(line) + 1  # +1 补回 split 吃掉的换行，近似分块累计口径
        if acc >= _CANARY_INTERVAL_CHARS:
            out.append(token)
            acc = 0
            inserted = True
    if not inserted:
        out.append(token)  # 短文兜底：至少 1 个令牌
    return "\n".join(out)


def find_canaries(content: str) -> list:
    """提取文本中全部 canary 令牌（8 位 hex 列表，含重复）"""
    return _CANARY_TOKEN_RE.findall(content)


async def record_canary(doc_id: int, canary: str, source_url: str) -> None:
    """canary 映射落库 crawl_canaries（全异常 warning 不上抛，不阻断入库主链路）

    Args:
        doc_id: ingest 返回的文档 ID（无 id 时调用方不触发本函数）
        canary: 8 位 hex 令牌
        source_url: 抓取来源 URL
    """
    try:
        from src.database import async_session_factory

        async with async_session_factory() as session:
            await session.execute(
                sql_text("INSERT INTO crawl_canaries (doc_id, canary, source_url) "
                         "VALUES (:d, :c, :s)"),
                {"d": doc_id, "c": canary, "s": source_url},
            )
            await session.commit()
    except Exception as e:
        logger.warning("canary 映射落库失败（fail-open，不影响入库主链路）: %s", e)


async def check_canary_leak(content: str) -> None:
    """输出侧 canary 泄漏检测（chat 两主路径接线点；全异常 fail-open）

    命中已登记令牌 → warning + record_span("canary_leak", "security",
    decision="doc_id=… source=…", status="blocked")（module-088 既有通道，
    无请求上下文时 span 静默跳过）。未登记令牌（历史残留/外部巧合）静默跳过。

    Args:
        content: 待检文本（chat 生成的 answer / 流式 answer_text）
    """
    tokens = find_canaries(content)
    if not tokens:
        return
    try:
        from src.database import async_session_factory

        async with async_session_factory() as session:
            for canary in dict.fromkeys(tokens):  # 去重保序
                row = (await session.execute(
                    sql_text("SELECT doc_id, source_url FROM crawl_canaries "
                             "WHERE canary = :c LIMIT 1"),
                    {"c": canary})).fetchone()
                if row is None:
                    continue
                source = str(row[1])[:100]
                logger.warning("canary 泄漏: doc_id=%s source=%s canary=%s",
                               row[0], source, canary)
                tracing.record_span("canary_leak", "security",
                                    decision=f"doc_id={row[0]} source={source}",
                                    status="blocked")
    except Exception as e:
        logger.warning("canary 泄漏检测失败（fail-open，不影响回答链路）: %s", e)
