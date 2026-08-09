"""
应用配置管理
使用 pydantic-settings 从环境变量读取配置
"""
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

    # Agent 工具化（module-028）：ReAct 循环工具总调用次数预算（防空转烧钱）
    max_agent_tools: int = 4

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

    # 意图分类（module-043 L4）：true 时 router 尝试加载 bge-m3+逻辑回归分类器
    #（模型缺失/加载失败自动回退 LLM 分类，零影响）；默认 false = 保持 LLM
    intent_classifier_enabled: bool = False

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

    model_config = {"env_prefix": "PW_", "env_file": ".env"}


settings = Settings()
