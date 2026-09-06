"""
module-086 注入防护量化评估 — 22 恶意 + 4 良性用例跑 sanitize 管线，拦截率/误伤率落库
===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== =====

用法（在 ai_service 目录下）:
    .venv/Scripts/python.exe eval/benchmarks/eval_injection.py

拦截口径（plan 裁定 5，确定性计算零 LLM 零网络，可复跑）:
  - 载体族（html_comment/script_style/hidden_unicode）：intercepted = 清洗后
    文本中该载体模式不再命中
  - 指令族（instruction_override/exfiltration/destructive_tool/hidden_text）：
    strip 模式 intercepted = findings 命中记录；strict 模式 intercepted = rejected
  - 良性 FP = strict 模式 rejected=True（strip 按构造不损可见正文，无 FP 面）
  - 已知语义：良性③（CSS 关键词讲解）hidden_text 字面命中 → strict 拒收计入
    FP 并在报告注记归因（默认档取 strip 的原因），禁调用例凑分。

落库: eval_runs(eval_type='injection')，scores 为 strip/strict 两模式六指标，
per_question 每用例 1 行（26 行）携带双模式明细（module-019/066 先例）。
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # 支持直接脚本执行（AC-15 命令口径）

from rag.crawl.sanitize import (
    _HTML_COMMENT_RE,
    _HIDDEN_UNICODE_RE,
    _SCRIPT_STYLE_RE,
    sanitize_crawl_content,
)
from eval.golden.golden_retrieval import get_git_commit, save_eval_run

CASES_PATH = Path(__file__).resolve().parents[1] / "datasets" / "injection_cases.json"
_CARRIER_RES = {"html_comment": _HTML_COMMENT_RE,
                "script_style": _SCRIPT_STYLE_RE,
                "hidden_unicode": _HIDDEN_UNICODE_RE}


def load_cases() -> dict:
    """加载用例集并校验结构（版本化 + 字段齐全 + 数量达标，失败报错退出）"""
    data = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    cases = data.get("cases")
    if not data.get("version") or not isinstance(cases, list):
        raise ValueError("injection_cases.json 结构非法：缺 version 或 cases")
    for c in cases:
        if not all(k in c for k in ("id", "category", "kind", "content")):
            raise ValueError(f"用例缺字段: {c.get('id', '?')}")
    poison = [c for c in cases if c["kind"] == "poison"]
    benign = [c for c in cases if c["kind"] == "benign"]
    if len(poison) < 20 or len(benign) < 4:
        raise ValueError(f"用例数不足: poison={len(poison)}(<20) benign={len(benign)}(<4)")
    return data


def _intercepted(case: dict, result, mode: str) -> bool:
    """裁定 5 口径：载体=清洗后模式不再命中；指令族 strip=findings/strict=rejected"""
    if case["category"] in _CARRIER_RES:
        return _CARRIER_RES[case["category"]].search(result.cleaned_text) is None
    if mode == "strict":
        return result.rejected
    return any(f["category"] == case["category"] for f in result.findings)


def evaluate(cases: list) -> tuple:
    """strip/strict 双模式全量评估：scores 六指标 × 2 + per_question（每用例 1 行）"""
    poison = [c for c in cases if c["kind"] == "poison"]
    benign = [c for c in cases if c["kind"] == "benign"]
    scores = {m: {"poison_total": len(poison), "intercepted": 0,
                  "benign_total": len(benign), "false_positives": 0}
              for m in ("strip", "strict")}
    per_question = []
    for c in cases:
        entry = {"id": c["id"], "category": c["category"], "kind": c["kind"]}
        for mode in ("strip", "strict"):
            r = sanitize_crawl_content(c["content"], mode)
            hit = _intercepted(c, r, mode)
            if c["kind"] == "poison" and hit:
                scores[mode]["intercepted"] += 1
            if c["kind"] == "benign" and r.rejected and mode == "strict":
                scores[mode]["false_positives"] += 1
            entry[mode] = {"intercepted": hit, "rejected": r.rejected,
                           "findings": [f["category"] for f in r.findings]}
        per_question.append(entry)
    for s in scores.values():
        s["interception_rate"] = round(s["intercepted"] / s["poison_total"], 4)
        s["false_positive_rate"] = round(s["false_positives"] / s["benign_total"], 4)
    return scores, per_question


def print_report(scores: dict, per_question: list) -> None:
    """控制台汇总表 + strict FP 归因注记（诚实上报，不凑分）"""
    print("=" * 64)
    print("module-086 注入防护量化评估（sanitize 管线，确定性零 LLM 零网络）")
    for mode in ("strip", "strict"):
        s = scores[mode]
        print(f"[{mode}] 恶意 {s['poison_total']} 条 拦截 {s['intercepted']} "
              f"拦截率 {s['interception_rate']} | 良性 {s['benign_total']} 条 "
              f"误伤 {s['false_positives']} 误伤率 {s['false_positive_rate']}")
    fp_ids = [e["id"] for e in per_question
              if e["kind"] == "benign" and e["strict"]["rejected"]]
    if fp_ids:
        print(f"注记: strict 误伤用例 {fp_ids} —— hidden_text 字面命中已知语义"
              "（良性③ CSS 关键词讲解），默认档 strip 不拒收，归因见 plan 裁定 5")
    print("=" * 64)


async def main() -> None:
    data = load_cases()
    scores, per_question = evaluate(data["cases"])
    print_report(scores, per_question)
    saved_id = await save_eval_run(
        eval_type="injection", git_commit=get_git_commit(),
        config_snapshot={"mode": "both", "case_version": data["version"]},
        scores=scores, per_question=per_question)
    if saved_id:
        print(f"已落库 eval_runs id={saved_id} (eval_type='injection')")
    else:
        print("警告: eval_runs 落库失败（DB 不可用？），控制台结果仍有效")


if __name__ == "__main__":
    asyncio.run(main())
