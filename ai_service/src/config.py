"""
应用配置管理
使用 pydantic-settings 从环境变量读取配置
"""
from typing import Literal

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # 应用
    app_name: str = "Personal Website AI Service"
    app_version: str = "0.1.0"
    debug: bool = False

    # 数据库
    database_url: str = "postgresql+asyncpg://postgres:postgres123@localhost:5432/personal_website"

    # Redis 缓存
    redis_url: str = "redis://localhost:6379/0"

    # LLM 供应商
    # fallback: 按 fallback_chain 顺序自动降级（默认 qwen → zhipu → deepseek）
    # 单供应商: claude | deepseek | qwen | zhipu | modelscope
    llm_provider: str = "fallback"

    # 降级链（逗号分隔，仅 llm_provider=fallback 时生效）
    fallback_chain: str = "qwen,zhipu,deepseek"

    # Claude
    claude_api_key: str = ""
    claude_model: str = "claude-sonnet-5-20251001"

    # DeepSeek
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-chat"
    deepseek_base_url: str = "https://api.deepseek.com/v1"

    # Qwen (通过 ModelScope API，默认首选)
    qwen_model: str = "Qwen/Qwen3.5-35B-A3B"

    # ZhipuAI GLM (通过 ModelScope API，Qwen 降级备用)
    zhipu_model: str = "ZhipuAI/GLM-5.2"

    # ModelScope（魔搭）
    modelscope_api_key: str = ""
    modelscope_model: str = "deepseek-ai/DeepSeek-V4-Pro"
    modelscope_base_url: str = "https://api-inference.modelscope.cn/v1"

    # 文本嵌入（默认使用 ModelScope 云端 API）
    embedding_api_key: str = ""
    embedding_base_url: str = ""
    embedding_model: str = "OllmOne/bge-m3-GGUF"

    # JWT 登录（module-032）：HS256 共享密钥，与 Java 后端一致
    # 环境变量：PW_JWT_SECRET（.env 本地配置，不进仓库）
    jwt_secret: str = ""

    # 混合检索
    hybrid_search_alpha: float = 0.3  # BM25 权重，向量权重为 1-alpha

    # 检索融合模式（module-053 三通道融合验证，module-055 切默认 rrf）：
    #   hybrid   —— 两通道 min-max 加权（FTS+向量），module-055 起为回退开关
    #   rrf      —— 三通道（FTS/向量/图谱）Reciprocal Rank Fusion，
    #                score(d) = Σ 1/(k + rank_i(d))，k=60 业界默认；
    #                图谱通道仅 round 0 语义参与融合（引擎层 round 1/2 单路混合）
    #   weighted —— 三通道 min-max 归一化 + 权重加权（retrieval_fusion_weights）
    # module-053 实测（golden 112 题同口径，见 specs/module-053-rrf-fusion/
    # changelog.md 对比表）：rrf Hit@5=0.9905 > 基线 hybrid 两通道 0.9714
    # （+0.0191，0 回退）> 加权两组 = 基线 —— **rrf 放行**。
    # module-054 清障：向量化降级方案 A/B（rrf 向量路失败 = FTS+图谱照常、
    # 引擎补图兜底）+ 引擎 rrf 真实 HTTP E2E 通过（chat/stream 全链路）。
    # module-055 决策：默认 hybrid→rrf（前置清障全部完成；存量 2 项降级
    # 用例在 module-054 方案 A/B 落地后已消解，零断言改动）。回退方式：
    # PW_RETRIEVAL_FUSION_MODE=hybrid 一键回退（保留开关）。
    # minor 修复（module-053）：Literal 枚举校验——非法字符串（拼写错误）
    # 启动即抛 ValidationError（fail-fast），防静默落入 rrf 分支（rrf 每次
    # 知识库查询 +1 次 LLM 实体提取调用，静默走错分支代价高）。
    retrieval_fusion_mode: Literal["hybrid", "rrf", "weighted"] = "rrf"
    # 加权融合权重（逗号分隔：FTS,向量,图谱；仅 retrieval_fusion_mode=weighted 生效）
    retrieval_fusion_weights: str = "0.3,0.6,0.1"
    # RRF 常数 k（业界默认 60；本模块不做 k 扫描，扫 k 留后续）
    rrf_constant_k: int = 60

    # Agent 工具化（module-028）：ReAct 循环工具总调用次数预算（防空转烧钱）
    max_agent_tools: int = 4

    # 工具阶段切分（module-058 / ADR-0012 方案 A，原 module-059 并入）：
    # 按 ctx.phase 状态机只暴露当前阶段工具（检索组 7 / 生成组 4，re_search
    # 双组）——省 schema token + 结构性防误调（检索阶段调不到 generate/
    # verify，不再靠工具内部字符串防御）。默认 true；false 回退全量 10 个
    # 零回归（逃生口）。测试环境由 conftest autouse fixture 钉住 false。
    tool_phase_split: bool = True

    # 请求可观测性（module-058 WP-C）：trace_id + 阶段计时 + token 用量 +
    # 缓存命中 → request_logs 落库（init_db 自愈幂等 DDL）。默认 true；
    # false 时零埋点零落库（中间件不初始化观测上下文、helper 直接返回）。
    # 测试环境由 conftest autouse fixture 钉住 false（测试不污染落库）。
    request_logs_enabled: bool = True

    # 长期记忆（module-033/035）：提取 / 去重 / 动态K 阈值（参考 llm-push/19-Agent记忆管理）
    memory_importance_threshold: float = 0.6    # 提取事实 importance < 0.6 丢弃
    # module-035 校准：真实 bge-m3 同义改写 cosine≈0.88，0.95 太严导致漏去重 → 下调 0.85
    memory_dedup_threshold: float = 0.85        # 语义去重：与本身份现有记忆 cosine > 0.85 视为重复
    memory_recall_high_threshold: float = 0.85  # 候选平均绝对余弦 > 0.85 → 召回 5 条
    memory_recall_mid_threshold: float = 0.75   # 0.75-0.85 → 召回 3 条；<0.75 → 1 条（宁缺毋滥）
    memory_max_recall: int = 5                  # 动态 K 上限
    # module-035：低分过滤阈值（绝对余弦口径）——低于该值的候选丢弃，防"本批相对高但绝对烂"注入
    memory_recall_min_score: float = 0.4

    # 短期记忆 + 会话记忆（module-034）
    memory_short_ttl_days: int = 7              # 短期记忆 TTL（天）：module-046 起由衰减+硬上限替代，保留兼容
    memory_session_max_messages: int = 50       # 每 identity 会话持久化消息上限（超限滚动删除最旧）
    memory_session_history_limit: int = 20      # 会话恢复注入生成的最近消息数

    # 短期记忆进化（module-046 / ADR-0007 问题 2）：强化/衰减/升级可配
    memory_short_half_life: float = 3.0         # 平滑衰减半衰期（天）：decay = 0.5**(age_days/half_life)
    memory_short_max_days: int = 30             # 硬上限（天）：last_mentioned_at/created_at 超上限不参与召回
    memory_mention_boost_alpha: float = 0.2     # 提及加权系数：最终分 = 语义分×decay×(1+α×mention_count)
    memory_promote_mentions: int = 2            # 短期→长期升级：mention_count ≥ 该值
    memory_promote_window_days: int = 7         # 升级窗口（天）：最近提及在窗口内才升级

    # 记忆冲突消解（module-061 / ADR-0007 P1）：true 时 _merge_duplicate 去重
    # 命中后走 mDeBERTa NLI 判矛盾（contradiction → 旧父块标 superseded=true +
    # 新内容按正常新增入库，替代"拼接共存"）；false 完全旧行为（追加拼接，零回归）。
    # 默认 false = 不预设成功：评测（eval/memory_conflict_dataset.py 矛盾 P/R/F1）
    # 达标（contradiction Recall≥0.8 且 Precision≥0.8）后才切 true，对齐
    # ADR-0003 L4 / module-052 放行模式。NLI 不可用/超时 → 返回 None → 旧行为。
    memory_conflict_enabled: bool = False

    # 意图分类（module-043 L4）：true 时 router 尝试加载 bge-m3+逻辑回归分类器
    #（模型缺失/加载失败自动回退 LLM 分类，零影响）。
    # module-056 达标启用：人造标注集 337 条重训 + golden_intent 100 条真实
    # 评测（LLM 1.0000 / 分类器 1.0000，eval_runs id=23/24）→ 默认开；
    # 回退开关：PW_INTENT_CLASSIFIER_ENABLED=false 保持 LLM 路径
    intent_classifier_enabled: bool = True

    # 反思充分性自洽性检查（module-044 层 2）：true 时 check_sufficiency 对
    # 同一 query 用两个不同温度各判一次，两次不一致 → 保守判充分（防漏检）；
    # 默认 false = 零额外 LLM 调用（成本翻倍，按需开启）
    sufficiency_self_check_enabled: bool = False

    # 反思充分性硬闸门阈值（module-048，module-047 实测数据结论）：
    # check_sufficiency 层 1 top-1 abs_cosine < 该值 → 直接判不充分（零 LLM）。
    # module-047 阈值扫描：0.4 漏判 60% 不充分；0.55 切在分布间隙上缘
    #（充分 min 0.490 / 不充分 max 0.550），F1=0.98 最优且误杀与 0.5 相同
    #（1/50）。不得改回 0.4（红线）。
    sufficiency_gate_threshold: float = 0.55

    # 分诊式 Query 改写（module-049 / ADR-0009）：
    # 静态分诊（FTS 术语命中 → 精确 query 直接检索，零成本不走改写）+ 模糊
    # query 走 LLM 改写 + 保真预检（改写 vs 原 query 余弦 < 阈值 → 回退原话，
    # 省一次检索）+ 并行检索择优（改写检索 top-1 绝对余弦 > 原检索 → 用改写
    # 结果，否则回退原结果）。改写链路任何一环失败 → 回退原 query（零回归）。
    # 默认关闭（与 intent_classifier_enabled 同款 opt-in 模式，保证零回归）；
    # 开启方式：PW_QUERY_REWRITE_ENABLED=true
    query_rewrite_enabled: bool = False
    rewrite_fidelity_threshold: float = 0.6  # 保真预检阈值：改写与原 query 余弦低于该值 → 回退原话

    # 答案验证裁判（module-051 / ADR-0010 P0-②）：
    # verify_answer 的 verdict 判定模型——"hhem"（默认）：LLM 拆句 + HHEM-2.1-Open
    # 批量判分（module-050 实测中文 Accuracy 0.77 显著胜出 MiniCheck 0.51，选型已定）；
    # "llm"：完全不加载 HHEM，直走旧逻辑（零回归开关）。HHEM 不可用（缺失/加载失败/
    # 推理异常）自动降级 LLM 判分，降级链保证默认 "hhem" 零风险。
    verify_judge_model: str = "hhem"
    # HHEM 三态映射阈值（经验值，标注集可校准）：每 claim 对每文档打分取 max →
    # max_score ≥ high → supported；low ≤ max_score < high → inferred；< low → unsupported
    verify_hhem_threshold_high: float = 0.7
    verify_hhem_threshold_low: float = 0.3

    # verify 异步化（module-060）：true（默认）——chat_stream 流式生成完不再
    # 同步 await verify（15-50s 阻塞主链路尾部），改 submit 后台任务 + done 事件
    # 带 verify_task_id + 前端轮询 GET /ai/rag/chat/verify/{task_id} 补结果，
    # 结果落 verify_results 表持久化（done 不因重启丢失）。false 回退现状同步
    # 路径（verified→done 事件逐字一致，逃生口）。测试环境由 conftest autouse
    # fixture 钉住 false（存量 chat_stream 测试零漂移）。
    verify_async_enabled: bool = True

    model_config = {"env_prefix": "PW_", "env_file": ".env"}


settings = Settings()
