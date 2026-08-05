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

    # 长期记忆（module-033）：提取 / 去重 / 动态K 阈值（参考 llm-push/19-Agent记忆管理）
    memory_importance_threshold: float = 0.6    # 提取事实 importance < 0.6 丢弃
    memory_dedup_threshold: float = 0.95        # 语义去重：与本身份现有记忆 cosine > 0.95 视为重复
    memory_recall_high_threshold: float = 0.85  # 候选平均相似度 > 0.85 → 召回 5 条
    memory_recall_mid_threshold: float = 0.75   # 0.75-0.85 → 召回 3 条；<0.75 → 1 条（宁缺毋滥）
    memory_max_recall: int = 5                  # 动态 K 上限

    model_config = {"env_prefix": "PW_", "env_file": ".env"}


settings = Settings()
