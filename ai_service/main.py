"""
AI 推理服务入口 — 张三个人网站
FastAPI + pgvector + LangChain 多供应商 LLM
"""
import logging
import json
import time
from collections import defaultdict
from typing import Optional

from contextlib import asynccontextmanager
from fastapi import FastAPI, Body, File, Form, UploadFile, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel

from src.config import settings
from src.database import init_db, async_session_factory
from src.ratelimit import check_rate_limit, get_client_ip
from src.cache import cache
from rag.engine import rag_engine
from rag.schemas import (
    SearchRequest, SearchResponse, ChatRequest, ChatResponse,
    MemorySaveRequest, MemoryRecallRequest,
)
from rag.models import Document
from rag.memory import memory_service
from llm.client import LLMFactory


# ─── IP 会话缓存 ───
# 结构: {client_ip: [{"role": str, "content": str, "timestamp": float}, ...]}
# 每个 IP 最多保存 MAX_MESSAGES_PER_IP 条
IP_SESSION_MESSAGES: dict[str, list[dict]] = defaultdict(list)
MAX_MESSAGES_PER_IP = 50

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("ai_service")


class ChainUpdateRequest(BaseModel):
    """LLM 降级链调整请求体（module-029 动态调序）

    Attributes:
        chain: 供应商顺序列表（如 ["zhipu", "deepseek", "qwen"]）
    """
    chain: list[str]


async def load_fallback_chain_from_redis() -> None:
    """启动时从 Redis 加载持久化降级链（module-029）

    优先级：Redis 中用户调整过的顺序 > 配置默认（.env PW_FALLBACK_CHAIN）。
    Redis 不可用 / 无链 / 存储链不合法时静默降级为配置默认（不改任何状态），
    不阻塞服务启动。

    调用时机：lifespan 中 LLM 客户端预热之前，确保预热即用持久化链。
    """
    try:
        raw = await cache.get_str("llm:fallback_chain")
    except Exception as e:
        logger.warning("读取 Redis 降级链失败，使用配置默认: %s", e)
        return
    if not raw:
        return
    try:
        chain = LLMFactory.validate_chain(
            [p.strip() for p in raw.split(",") if p.strip()]
        )
    except ValueError as e:
        logger.warning("Redis 降级链不合法，使用配置默认: %s", e)
        return
    LLMFactory.set_fallback_chain(chain)
    logger.info("从 Redis 加载降级链: %s", " → ".join(chain))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("AI 服务启动中...")
    await init_db()

    # 预热 embedding 模型 + LLM 客户端，避免首次请求卡顿
    from rag.embeddings import embedding_service
    logger.info("预热 embedding 模型中...")
    await embedding_service.embed_text("warmup")
    logger.info("embedding 模型已就绪")

    from llm.client import LLMFactory
    # 先加载 Redis 中持久化的降级链（module-029），无则用配置默认，
    # 确保后续 LLM 预热/调用都使用最新顺序
    await load_fallback_chain_from_redis()
    logger.info("预热 LLM 客户端...")
    try:
        LLMFactory.get_client()  # 触发默认 provider（fallback 降级链）
        logger.info("LLM 客户端已预热 (default/fallback)")
    except Exception as e:
        logger.warning("LLM 客户端预热失败（可接受）: %s", e)

    # 预热 Qwen + Zhipu（ModelScope 降级链的前两环），避免首次调用冷启动
    for label, provider in [("Qwen", "qwen"), ("ZhipuAI GLM", "zhipu")]:
        try:
            LLMFactory.get_client(provider)
            logger.info("%s 客户端已预热", label)
        except Exception as e:
            logger.warning("%s 预热失败（可接受）: %s", label, e)

    yield
    logger.info("AI 服务关闭")


app = FastAPI(
    title=settings.app_name,
    description="Agentic RAG 知识库推理服务",
    version=settings.app_version,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── IP 限流中间件（除 health 外所有请求） ───
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """基于 IP 的请求频率限制

    在请求进入路由之前检查限流，超出阈值返回 429。
    同时提取客户端 IP 注入 request.state 供后续使用。
    """
    # 健康检查不限制
    if request.url.path == "/ai/health":
        return await call_next(request)

    # 提取客户端 IP
    forwarded = request.headers.get("X-Forwarded-For")
    client_ip = get_client_ip(forwarded, request.client.host if request.client else None)
    request.state.client_ip = client_ip

    # 限流检查
    allowed, retry_after = check_rate_limit(client_ip)
    if not allowed:
        return JSONResponse(
            status_code=429,
            content={"message": f"请求过于频繁，请 {retry_after} 秒后重试", "retry_after": retry_after},
            headers={"Retry-After": str(retry_after)},
        )

    return await call_next(request)


# ─── 保存消息到 IP 会话缓存 ───
def save_messages_to_session(client_ip: str, user_msg: str, assistant_msg: str, assistant_sources: list):
    """把一次问答追加到 IP 会话记录中，超出上限时丢弃最旧消息"""
    records = IP_SESSION_MESSAGES[client_ip]
    now = time.time()
    records.append({"role": "user", "content": user_msg, "timestamp": now})
    records.append({"role": "assistant", "content": assistant_msg, "sources": assistant_sources, "timestamp": now})
    # 裁剪超出部分
    if len(records) > MAX_MESSAGES_PER_IP:
        IP_SESSION_MESSAGES[client_ip] = records[-MAX_MESSAGES_PER_IP:]


@app.get("/ai/health")
async def health():
    """健康检查"""
    return {"status": "ok", "service": "ai-service"}


@app.get("/ai/config")
async def get_config():
    """返回当前配置（不含密钥）"""
    return {
        "provider": settings.llm_provider,
        "claude_model": settings.claude_model,
        "deepseek_model": settings.deepseek_model,
        "debug": settings.debug,
    }


# ─── LLM 降级链动态调序 API（module-029） ───


@app.get("/ai/llm/chain")
async def get_llm_chain():
    """获取当前 LLM 降级链顺序

    返回运行时链（Redis 持久化的用户配置优先），否则配置默认
    （.env PW_FALLBACK_CHAIN）。

    返回格式: {"code": 0, "data": {"chain": ["qwen", "zhipu", "deepseek"]}}
    """
    return {"code": 0, "data": {"chain": LLMFactory.get_fallback_chain()}}


@app.put("/ai/llm/chain")
async def put_llm_chain(request: ChainUpdateRequest):
    """调整 LLM 降级链顺序（校验 → 存 Redis → 清缓存即时生效）

    流程：
      1. 校验链合法（非空、全为支持供应商、无重复）
      2. 写入 Redis（key: llm:fallback_chain，无 TTL 跨重启持久）
      3. 更新运行时链 + clear_cache → 下次 get_client("fallback") 按新链重建

    Redis 写入失败时返回 code 2 且不修改运行时链（调序不生效但服务正常）。

    Args:
        request: {chain: ["zhipu", "deepseek", "qwen"]}

    Returns:
        code=0: {"code": 0, "data": {"chain": [...]}}
        code=1: 校验失败（非法供应商/重复/空链）
        code=2: Redis 持久化失败
    """
    try:
        validated = LLMFactory.validate_chain(request.chain)
    except ValueError as e:
        return {"code": 1, "message": str(e)}

    saved = await cache.set_str("llm:fallback_chain", ",".join(validated))
    if not saved:
        return {"code": 2, "message": "降级链保存失败（Redis 不可用），顺序未修改"}

    LLMFactory.set_fallback_chain(validated)
    LLMFactory.clear_cache()
    logger.info("降级链已更新并持久化: %s", " → ".join(validated))
    return {"code": 0, "data": {"chain": validated}}


# ─── IP 会话管理 API ───


@app.get("/ai/chat/sessions")
async def get_chat_sessions():
    """获取当前活跃的 IP 会话列表

    只返回元信息（IP、消息数、最后活跃时间），不返回消息内容。
    """
    sessions = []
    for ip, messages in IP_SESSION_MESSAGES.items():
        if messages:
            sessions.append({
                "id": ip,
                "message_count": len(messages),
                "last_active": messages[-1].get("timestamp", 0),
            })
    # 按最后活跃时间降序排列
    sessions.sort(key=lambda s: s["last_active"], reverse=True)
    return {"data": sessions}


@app.get("/ai/chat/sessions/{ip}/messages")
async def get_session_messages(ip: str):
    """获取指定 IP 的会话消息列表

    返回的消息不带 timestamp（前端不需要），带 sources。
    """
    messages = IP_SESSION_MESSAGES.get(ip, [])
    # 去掉 timestamp 字段，前端不需要
    clean = []
    for msg in messages:
        entry = {"role": msg["role"], "content": msg["content"]}
        if msg.get("sources"):
            entry["sources"] = msg["sources"]
        clean.append(entry)
    return {"data": clean, "count": len(clean)}


@app.post("/ai/rag/search", response_model=SearchResponse)
async def search(request: SearchRequest):
    """RAG 知识库检索"""
    return await rag_engine.search(request)


@app.post("/ai/rag/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, fastapi_req: Request):
    """RAG 知识库问答（自动保存会话到 IP 缓存）

    将客户端 IP 传给 rag_engine.chat，用于按 IP 隔离检索长期记忆
    （module-023；无记忆时零回归）。
    """
    client_ip = getattr(fastapi_req.state, "client_ip", "unknown")
    result = await rag_engine.chat(request, client_ip=client_ip)
    # 保存消息到 IP 会话缓存（仅知识库路径保存）
    if result.message not in ("casual_chat", "realtime_not_implemented") and result.answer:
        save_messages_to_session(client_ip, request.query, result.answer, result.sources)
    return result


@app.post("/ai/rag/chat/stream")
async def chat_stream(request: ChatRequest, fastapi_req: Request):
    """RAG 知识库问答（流式输出）

    先完成前置步骤（意图→检索→Rerank→反思），每步结果通过 SSE step 事件推送，
    LLM 生成部分通过 token 事件逐字输出。

    长期记忆（module-025）：流式路径在 Step 5 生成前调用
    rag_engine._recall_memory 召回跨会话记忆（5s 超时 + 失败降级返回空串），
    无记忆时 memory 为空串，行为与之前完全一致（零回归）。

    SSE 事件：
      event: step   data: {"step":str, "data":dict, "timing_ms":int}
      event: token  data: "文本片段"
      event: done   data: {"sources":[...]}
      event: error  data: {"message":str}
    """
    # client_ip 由限流中间件注入 request.state（module-023 透传），取不到默认 'unknown'
    client_ip = getattr(fastapi_req.state, "client_ip", "unknown")

    async def event_stream():
        import time
        _t = time.monotonic
        try:
            # ====== Step 1: 意图识别 ======
            t0 = _t()
            from agent.router import router_agent
            intent_result = await router_agent.classify(request.query)
            intent = intent_result.get("intent", "knowledge")
            intent_labels = {"knowledge": "知识库", "casual_chat": "闲聊", "realtime": "实时数据"}
            step_data = json.dumps({
                "step": "intent",
                "data": {"label": intent_labels.get(intent, intent), "confidence": intent_result.get("confidence", 0)},
                "timing_ms": int((_t() - t0) * 1000),
            })
            yield f"event: step\ndata: {step_data}\n\n"

            if intent == "casual_chat":
                from llm.client import LLMFactory
                client = LLMFactory.get_client()
                async for token in client.generate_stream(
                    f"你是张三个人网站的 AI 助手。\n用户: {request.query}"
                ):
                    yield f"event: token\ndata: {json.dumps(token)}\n\n"
                yield "event: done\ndata: {}\n\n"
                return

            # ====== Step 2: 检索 ======
            t0 = _t()
            docs = await rag_engine._retrieve(request.query, top_k=20)
            retrieval_count = len(docs)
            # 预览文档（前5条标题+摘要）
            previews = []
            relevant_count = 0
            MIN_SCORE = 0.3
            for d in docs:
                score = d.get("hybrid_score", 0)
                if score >= MIN_SCORE:
                    relevant_count += 1
                if len(previews) < 5:
                    previews.append({
                        "title": d.get("title", ""),
                        "snippet": d.get("content", "")[:80],
                        "score": round(score, 3),
                    })
            step_data = json.dumps({
                "step": "retrieval",
                "data": {"count": retrieval_count, "relevant": relevant_count, "previews": previews},
                "timing_ms": int((_t() - t0) * 1000),
            })
            yield f"event: step\ndata: {step_data}\n\n"

            if not docs:
                from llm.client import LLMFactory
                client = LLMFactory.get_client()
                async for token in client.generate_stream(
                    f"用户问：{request.query}\n\n知识库暂无相关信息。"
                ):
                    yield f"event: token\ndata: {json.dumps(token)}\n\n"
                yield "event: done\ndata: {}\n\n"
                return

            # ====== Step 3: Rerank ======
            t0 = _t()
            rerank_before = len(docs)
            docs = await rag_engine._rerank(request.query, docs)
            step_data = json.dumps({
                "step": "rerank",
                "data": {"before": rerank_before, "after": len(docs)},
                "timing_ms": int((_t() - t0) * 1000),
            })
            yield f"event: step\ndata: {step_data}\n\n"

            # ====== Step 4: 反思 ======
            t0 = _t()
            from agent.reflector import reflector
            check = await reflector.check_sufficiency(request.query, docs)
            reflection_data = {
                "sufficient": check.get("sufficient", True),
                "reason": check.get("reason", ""),
            }
            if not check.get("sufficient", True) and check.get("rewritten_query"):
                reflection_data["rewritten_query"] = check["rewritten_query"]
            step_data = json.dumps({
                "step": "reflection", "data": reflection_data,
                "timing_ms": int((_t() - t0) * 1000),
            })
            yield f"event: step\ndata: {step_data}\n\n"

            # ====== Step 5: 流式生成 ======
            # module-025: 流式路径接入长期记忆（复用 engine._recall_memory，
            # 5s 超时 + 失败降级返回空串；无记忆时 memory 为空串，零回归）
            memory = await rag_engine._recall_memory(request.query, client_ip)
            async for token in reflector.generate_answer_stream(request.query, docs, history=request.history, memory=memory):
                yield f"event: token\ndata: {json.dumps(token)}\n\n"

            # ====== Step 6: 引用溯源 ======
            sources = []
            for i, doc in enumerate(docs[:5]):
                sources.append({
                    "id": doc.get("id"),
                    "title": doc.get("title", ""),
                    "content": doc.get("content", "")[:300],
                    "source": doc.get("source", ""),
                    "ref_index": i + 1,
                })
            yield f"event: done\ndata: {json.dumps({'sources': sources})}\n\n"

        except Exception as e:
            logger.error("流式问答失败: %s", e, exc_info=True)
            yield f"event: error\ndata: {json.dumps({'message': '服务暂时不可用'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@app.post("/ai/rag/chat/agent")
async def chat_agent(request: ChatRequest, fastapi_req: Request):
    """Agent 工具化问答（ReAct 循环，SSE，module-028）

    把固定流水线升级为 Agentic ReAct 循环：LLM 自主决定调用哪些工具、以什么
    顺序，直到信息足够直接回答，或达到工具总调用次数预算（settings.max_agent_tools）。
    与现有 /ai/rag/chat、/ai/rag/chat/stream 并存（A/B 对比）。

    SSE 事件：
      event: tool_call    data: {"name", "args", "tool_count"}
      event: tool_result  data: {"name", "args", "result", "tool_count"}
      event: token        data: "推理/回答文本片段"
      event: done         data: {"answer", "sources", "tool_count", "budget"}
      event: error        data: {"message"}
    """
    client_ip = getattr(fastapi_req.state, "client_ip", "unknown")

    async def event_stream():
        from agent.react import ReactContext, _build_messages, react_loop
        try:
            ctx = ReactContext(request.query, client_ip, request.history)
            budget = settings.max_agent_tools
            answer = ""
            tool_count = 0
            async for evt in react_loop(ctx, _build_messages(ctx), budget):
                t = evt["type"]
                if t == "tool_call":
                    yield f"event: tool_call\ndata: {json.dumps({'name': evt['name'], 'args': evt['args'], 'tool_count': evt['tool_count']}, ensure_ascii=False)}\n\n"
                elif t == "tool_result":
                    yield f"event: tool_result\ndata: {json.dumps({'name': evt['name'], 'args': evt['args'], 'result': evt['result'][:500], 'tool_count': evt['tool_count']}, ensure_ascii=False)}\n\n"
                elif t == "token":
                    if evt["content"]:
                        yield f"event: token\ndata: {json.dumps(evt['content'], ensure_ascii=False)}\n\n"
                elif t == "done":
                    answer = evt.get("answer", "")
                    tool_count = evt.get("tool_count", 0)

            # 引用溯源：基于循环累积的已检索文档
            sources = []
            for i, doc in enumerate(ctx.docs[:5]):
                sources.append({
                    "id": doc.get("id"),
                    "title": doc.get("title", ""),
                    "content": doc.get("content", "")[:300],
                    "source": doc.get("source", ""),
                    "ref_index": i + 1,
                })
            yield f"event: done\ndata: {json.dumps({'answer': answer, 'sources': sources, 'tool_count': tool_count, 'budget': budget}, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.error("Agent 问答失败: %s", e, exc_info=True)
            yield f"event: error\ndata: {json.dumps({'message': '服务暂时不可用'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@app.post("/ai/rag/chat/agent-lg")
async def chat_agent_langgraph(request: ChatRequest, fastapi_req: Request):
    """LangGraph 实验端点（SSE，module-030）

    与 /ai/rag/chat/agent 并存：用 LangGraph StateGraph 编排 ReAct 循环
    （见 agent/langgraph_react.py），行为与手写版对齐（预算/工具/上下文），
    不动现有 react.py（零回归）。实验端点，非生产主路径。

    SSE 事件（与 agent 一致）：
      event: tool_call    data: {"name", "args", "tool_count"}
      event: tool_result  data: {"name", "args", "result", "tool_count"}
      event: token        data: "推理/回答文本片段"
      event: done         data: {"answer", "sources", "tool_count", "budget"}
      event: error        data: {"message"}
    """
    client_ip = getattr(fastapi_req.state, "client_ip", "unknown")

    async def event_stream():
        from agent.langgraph_react import (
            ReactContext, _build_messages, langgraph_react_loop,
        )
        try:
            ctx = ReactContext(request.query, client_ip, request.history)
            budget = settings.max_agent_tools
            answer = ""
            tool_count = 0
            async for evt in langgraph_react_loop(ctx, _build_messages(ctx), budget):
                t = evt["type"]
                if t == "tool_call":
                    yield f"event: tool_call\ndata: {json.dumps({'name': evt['name'], 'args': evt['args'], 'tool_count': evt['tool_count']}, ensure_ascii=False)}\n\n"
                elif t == "tool_result":
                    yield f"event: tool_result\ndata: {json.dumps({'name': evt['name'], 'args': evt['args'], 'result': evt['result'][:500], 'tool_count': evt['tool_count']}, ensure_ascii=False)}\n\n"
                elif t == "token":
                    if evt["content"]:
                        yield f"event: token\ndata: {json.dumps(evt['content'], ensure_ascii=False)}\n\n"
                elif t == "done":
                    answer = evt.get("answer", "")
                    tool_count = evt.get("tool_count", 0)

            # 引用溯源：基于循环累积的已检索文档（与 /ai/rag/chat/agent 一致）
            sources = []
            for i, doc in enumerate(ctx.docs[:5]):
                sources.append({
                    "id": doc.get("id"),
                    "title": doc.get("title", ""),
                    "content": doc.get("content", "")[:300],
                    "source": doc.get("source", ""),
                    "ref_index": i + 1,
                })
            yield f"event: done\ndata: {json.dumps({'answer': answer, 'sources': sources, 'tool_count': tool_count, 'budget': budget}, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.error("LangGraph Agent 问答失败: %s", e, exc_info=True)
            yield f"event: error\ndata: {json.dumps({'message': '服务暂时不可用'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


# ─── 长期记忆 API（module-023；复用 documents 表，source='memory:<ip>:' 区分） ───


@app.post("/ai/memory/save")
async def memory_save(request: MemorySaveRequest):
    """保存长期记忆（按 IP 隔离写入 documents，source='memory:<ip>:'）

    分块 → 本地 bge-m3 向量化 → 写 documents（父块 + 子块）。
    content 为空返回错误；embedding 不可用返回错误码（不崩）。
    """
    try:
        result = await memory_service.save(request.content, request.ip)
        return {"code": 0, "data": result}
    except ValueError as e:
        return {"code": 1, "message": str(e)}
    except Exception as e:
        logger.error("记忆保存失败: %s", e, exc_info=True)
        return {"code": 2, "message": "记忆保存失败"}


@app.post("/ai/memory/recall")
async def memory_recall(request: MemoryRecallRequest):
    """检索与 query 相关的长期记忆（按 IP 隔离，source 过滤）"""
    try:
        memories = await memory_service.recall(request.query, request.ip)
        return {"code": 0, "data": {"memories": memories}}
    except Exception as e:
        logger.error("记忆检索失败: %s", e, exc_info=True)
        return {"code": 1, "data": {"memories": []}, "message": "记忆检索失败"}


@app.post("/ai/rag/documents")
async def add_document(
    title: str = Body(...),
    content: str = Body(...),
    source: str = Body(default=""),
):
    """添加文档到知识库（向量化后自动入库）"""
    result = await rag_engine.add_document(title, content, source)
    return {"code": 0, "data": result}


@app.post("/ai/rag/documents/upload")
async def upload_document(
    file: UploadFile = File(...),
    title: str = Form(default=""),
    source: str = Form(default=""),
):
    """上传 PDF 文档，自动提取文本后入库

    上传 PDF 文件（multipart/form-data），可选附加标题和来源标识。
    使用 PyMuPDF 提取文本内容，调用已有 add_document 入库。
    """
    # 校验文件类型
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        return {"code": 1, "message": "仅支持 PDF 文件"}

    # 读取文件内容
    content_bytes = await file.read()
    if not content_bytes:
        return {"code": 2, "message": "上传文件为空"}

    # 用 PyMuPDF 解析
    try:
        import fitz

        pdf_doc = fitz.open(stream=content_bytes, filetype="pdf")
        page_count = pdf_doc.page_count
        pages_text = []
        for i, page in enumerate(pdf_doc, start=1):
            text = page.get_text()
            pages_text.append(f"--- Page {i}/{page_count} ---\n{text}")
        full_text = "\n\n".join(pages_text)
        pdf_doc.close()
    except ImportError:
        return {"code": 3, "message": "PDF 解析库不可用，请安装 PyMuPDF"}
    except Exception as e:
        logger.error("PDF 解析失败: %s", e, exc_info=True)
        return {"code": 3, "message": f"PDF 解析失败: {e}"}

    # 确定标题
    if not title:
        title = (
            file.filename.replace(".pdf", "")
            .replace("_", " ")
            .replace("-", " ")
            .strip()
        )

    # 确定来源
    if not source:
        source = f"pdf_upload:{file.filename}"

    # 调用已有 add_document 入库
    result = await rag_engine.add_document(title, full_text, source)
    result["page_count"] = page_count

    return {"code": 0, "data": result}


@app.get("/ai/documents")
async def list_documents(page: int = 1, page_size: int = 20):
    """查看知识库文档列表（分页，按原始标题聚类去重）"""
    from sqlalchemy import func, or_, select

    async with async_session_factory() as session:
        # 按原始标题分组取最旧 id 作为代表；
        # 排除记忆文档（source='memory:%'，module-023 复用 documents 表），
        # 避免记忆行污染知识库管理面板（review #7）
        subq = (
            select(
                Document.title,
                func.min(Document.id).label("min_id"),
                func.count(Document.id).label("chunk_count"),
            )
            .where(or_(Document.source.is_(None), Document.source.not_like("memory:%")))
            .group_by(Document.title)
            .subquery()
        )
        q = (
            select(Document, subq.c.chunk_count)
            .join(subq, Document.id == subq.c.min_id)
            .order_by(Document.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        total = (await session.execute(
            select(func.count()).select_from(subq)
        )).scalar() or 0
        rows = await session.execute(q)
        docs = []
        for doc, chunk_count in rows:
            docs.append({
                "id": doc.id,
                "title": doc.title,
                "source": doc.source or "",
                "content_preview": doc.content[:120] if doc.content else "",
                "chunk_count": chunk_count,
                "created_at": doc.created_at.isoformat() if doc.created_at else "",
            })

    return {"code": 0, "data": {"documents": docs, "total": total, "page": page, "page_size": page_size}}


@app.delete("/ai/documents/{doc_id}")
async def delete_document(doc_id: int):
    """删除文档及其所有相关分块"""
    from sqlalchemy import select as sel

    async with async_session_factory() as session:
        doc = await session.get(Document, doc_id)
        if not doc:
            return {"code": 1, "message": "文档不存在"}

        title = doc.title
        stmt = sel(Document).where(
            (Document.title == title) | (Document.title.like(f"{title} > %"))
        )
        rows = await session.execute(stmt)
        to_delete = rows.scalars().all()
        for d in to_delete:
            await session.delete(d)
        await session.commit()

    # 检索缓存失效：删除文档后结果可能变化，全量清空
    # 缓存是优化层，失效失败降级（delete_by_prefix 内部 catch，返回 False）
    await cache.delete_by_prefix("rag:retrieve:")

    logger.info("删除文档: id=%d, title=%s, chunks=%d", doc_id, title, len(to_delete))
    return {"code": 0, "message": f"已删除 {len(to_delete)} 条记录"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
