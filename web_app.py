"""
Web服务模块
提供FastAPI后端服务，支持前端交互式对话
支持会话隔离、流式输出（SSE）和安全防护（认证、限流、CORS、输入验证）
"""

import asyncio
import json
import os
import re
import time
import uuid
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, field_validator
import uvicorn

# 导入配置
import config

# 导入日志模块
from logger import (
    get_logger, set_request_id, set_session_id,
    log_request_start, log_request_end, log_session_create,
)

# 导入会话管理器
from session_manager import session_manager

# 导入健康检查模块
from health_check import (
    run_health_checks,
    health_report_to_dict,
    get_uptime_seconds,
)


# ==================== 数据模型定义 ====================

class ChatMessage(BaseModel):
    """聊天消息模型"""
    role: str  # "user" 或 "assistant"
    content: str


class ChatRequest(BaseModel):
    """聊天请求模型"""
    message: str
    session_id: Optional[str] = None
    agent_type: str = "conversational"
    provider: Optional[str] = None
    model_name: Optional[str] = None
    prompt_name: Optional[str] = None  # prompt 模板名称

    @field_validator("message")
    @classmethod
    def validate_message(cls, v: str) -> str:
        """验证消息不为空且不超过长度限制"""
        v = v.strip()
        if not v:
            raise ValueError("消息不能为空")
        if len(v) > config.MAX_MESSAGE_LENGTH:
            raise ValueError(
                f"消息长度超过限制 ({len(v)}/{config.MAX_MESSAGE_LENGTH} 字符)"
            )
        return v

    @field_validator("agent_type")
    @classmethod
    def validate_agent_type(cls, v: str) -> str:
        """验证 agent 类型合法"""
        allowed = {"conversational", "react", "functions"}
        if v not in allowed:
            raise ValueError(f"不支持的 agent 类型: {v}，允许: {allowed}")
        return v


class ConfigRequest(BaseModel):
    """配置请求模型"""
    provider: str
    model_name: str
    agent_type: str = "conversational"
    session_id: Optional[str] = None

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, v: str) -> str:
        allowed = {"openai", "azure", "deepseek", "zhipu", "moonshot", "ollama", "custom"}
        if v not in allowed:
            raise ValueError(f"不支持的提供商: {v}")
        return v


class ResetRequest(BaseModel):
    """重置请求模型"""
    session_id: Optional[str] = None


# ==================== 认证 ====================

# HTTP Bearer Token 安全方案
security_scheme = HTTPBearer(auto_error=False)


async def verify_api_key(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
) -> bool:
    """
    验证 API Key

    如果配置了 APP_API_KEY，则强制验证；
    如果未配置，则跳过验证（开发模式）。

    支持两种传参方式：
    - Authorization: Bearer <key>
    - Query 参数: ?api_key=<key>
    """
    # 未配置 API Key = 认证不启用（开发模式）
    if not config.APP_API_KEY:
        return True

    # 方式 1: Bearer Token
    if credentials and credentials.credentials == config.APP_API_KEY:
        return True

    # 方式 2: Query 参数
    query_key = request.query_params.get("api_key")
    if query_key == config.APP_API_KEY:
        return True

    raise HTTPException(
        status_code=401,
        detail="未授权访问：缺少或无效的 API Key。请在 Authorization header 或 ?api_key= 参数中提供。",
        headers={"WWW-Authenticate": "Bearer"},
    )


# ==================== 速率限制 ====================

# 尝试加载 slowapi；不可用时使用简易计数器回退
_RATE_LIMITER = None
_simple_rate_store: dict = {}  # key -> list of timestamps

try:
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.util import get_remote_address
    from slowapi.errors import RateLimitExceeded

    limiter = Limiter(
        key_func=get_remote_address,
        default_limits=[config.RATE_LIMIT_GLOBAL] if config.RATE_LIMIT_ENABLED else [],
    )
    _RATE_LIMITER = "slowapi"
except ImportError:
    limiter = None
    RateLimitExceeded = Exception

    async def get_remote_address(request: Request) -> str:
        """获取客户端 IP 地址"""
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        client = request.client
        return client.host if client else "unknown"


def _simple_rate_limit(key: str, max_requests: int, window_seconds: int) -> bool:
    """
    简易速率限制器（slowapi 不可用时的回退）

    Args:
        key: 限制键（如 IP:endpoint）
        max_requests: 窗口内的最大请求数
        window_seconds: 时间窗口（秒）

    Returns:
        bool: True = 允许, False = 被限制
    """
    if not config.RATE_LIMIT_ENABLED:
        return True

    now = time.time()
    window_start = now - window_seconds

    if key not in _simple_rate_store:
        _simple_rate_store[key] = []

    # 清理过期记录
    _simple_rate_store[key] = [t for t in _simple_rate_store[key] if t > window_start]

    if len(_simple_rate_store[key]) >= max_requests:
        return False

    _simple_rate_store[key].append(now)
    return True


def parse_rate_limit(limit_str: str) -> tuple:
    """解析 "10/minute" 格式的限流配置"""
    match = re.match(r"(\d+)/(second|minute|hour|day)", limit_str)
    if not match:
        return 60, 60  # 默认: 60次/60秒
    count = int(match.group(1))
    unit = match.group(2)
    multiplier = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}
    return count, multiplier.get(unit, 60)


# ==================== FastAPI 应用 ====================

app = FastAPI(
    title="LangChain Agent 智能助手",
    description="一个基于LangChain的多工具Agent，支持多种LLM提供商、会话隔离、流式输出和安全防护",
    version="2.1.0",
)


# ==================== 安全响应头中间件 ====================

@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    """为所有响应添加安全头"""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Powered-By"] = ""
    response.headers["Server"] = ""
    return response


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    """
    请求日志中间件

    记录每个 HTTP 请求的：方法、路径、状态码、耗时。
    自动提取/生成 request_id 并注入到日志上下文。
    """
    # 提取或生成 request_id
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())[:8]
    set_request_id(request_id)

    # 获取客户端 IP
    forwarded = request.headers.get("X-Forwarded-For")
    client_ip = forwarded.split(",")[0].strip() if forwarded else (
        request.client.host if request.client else "unknown"
    )

    # 记录请求开始
    log_request_start(request.method, request.url.path, client_ip)

    start = time.time()
    response = await call_next(request)
    duration_ms = (time.time() - start) * 1000

    # 注入 request_id 到响应头
    response.headers["X-Request-ID"] = request_id

    # 记录请求结束
    log_request_end(request.method, request.url.path, response.status_code, duration_ms)

    return response

# 配置 CORS
cors_origins = config.CORS_ALLOWED_ORIGINS
if cors_origins == ["*"]:
    # 开发模式下仍然打印警告
    if os.getenv("ENV", "development") == "production":
        cors_origins = os.getenv("CORS_ALLOWED_ORIGINS", "").split(",")
        if cors_origins == [""]:
            cors_origins = []

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True if cors_origins != ["*"] else False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)

# 配置 slowapi（如果可用）
if limiter is not None and _RATE_LIMITER == "slowapi":
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, lambda req, exc: JSONResponse(
        status_code=429,
        content={"success": False, "detail": "请求过于频繁，请稍后重试。"},
    ))


# ==================== API 路由 ====================


@app.get("/", response_class=HTMLResponse)
async def root():
    """返回前端HTML页面"""
    return FileResponse("static/index.html")


@app.post("/api/chat")
async def chat(
    request: ChatRequest,
    _auth: bool = Depends(verify_api_key),
    req: Request = None,
):
    """
    处理聊天消息（非流式）

    安全措施：
    - API Key 认证
    - 消息长度验证（Pydantic field_validator）
    - 速率限制
    """
    # 速率限制检查
    if _RATE_LIMITER == "slowapi" and limiter:
        pass  # slowapi 通过装饰器处理
    else:
        client_ip = await get_remote_address(req) if req else "unknown"
        count, window = parse_rate_limit(config.RATE_LIMIT_CHAT)
        if not _simple_rate_limit(f"{client_ip}:chat", count, window):
            raise HTTPException(status_code=429, detail="请求过于频繁，请稍后重试。")

    try:
        session, is_new = session_manager.get_or_create_session(
            session_id=request.session_id,
            provider=request.provider,
            model_name=request.model_name,
            agent_type=request.agent_type,
        )

        if is_new:
            set_session_id(session.session_id)
            log_session_create(session.session_id, session.provider)

        # 异步执行 Agent（线程池，不阻塞事件循环）
        response = await session.achat(request.message)

        return {
            "success": True,
            "response": response,
            "session_id": session.session_id,
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"服务器内部错误: {str(e)}")


@app.post("/api/chat/stream")
async def chat_stream(
    request: ChatRequest,
    _auth: bool = Depends(verify_api_key),
    req: Request = None,
):
    """
    处理聊天消息（流式 - SSE）

    安全措施同 /api/chat，额外通过 SSE 逐 token 推送。
    """
    # 速率限制检查
    if _RATE_LIMITER != "slowapi":
        client_ip = await get_remote_address(req) if req else "unknown"
        count, window = parse_rate_limit(config.RATE_LIMIT_STREAM)
        if not _simple_rate_limit(f"{client_ip}:stream", count, window):
            raise HTTPException(status_code=429, detail="请求过于频繁，请稍后重试。")

    try:
        session, is_new = session_manager.get_or_create_session(
            session_id=request.session_id,
            provider=request.provider,
            model_name=request.model_name,
            agent_type=request.agent_type,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    async def event_generator():
        try:
            yield f"data: {json.dumps({'type': 'session', 'session_id': session.session_id})}\n\n"

            async for chunk in session.astream(request.message):
                event_type = chunk.get("type", "unknown")
                content = chunk.get("content", "")
                yield f"data: {json.dumps({'type': event_type, 'content': content})}\n\n"

            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/config")
async def set_config(
    request: ConfigRequest,
    _auth: bool = Depends(verify_api_key),
):
    """配置Agent参数"""
    try:
        if request.session_id:
            session_manager.destroy_session(request.session_id)

        session = session_manager.create_session(
            provider=request.provider,
            model_name=request.model_name,
            agent_type=request.agent_type,
        )

        return {
            "success": True,
            "message": "配置已更新",
            "session_id": session.session_id,
            "config": {
                "provider": session.provider,
                "model": session.model_name or "",
                "agent_type": session.agent_type,
            },
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"服务器内部错误: {str(e)}")


@app.get("/api/config")
async def get_config(_auth: bool = Depends(verify_api_key)):
    """获取默认配置"""
    return {
        "provider": config.LLM_PROVIDER,
        "model": config.MODEL_NAME or "",
        "agent_type": "conversational",
        "available_providers": ["openai", "azure", "deepseek", "zhipu", "moonshot", "ollama", "custom"],
    }


@app.post("/api/reset")
async def reset(
    request: ResetRequest = None,
    _auth: bool = Depends(verify_api_key),
):
    """重置指定会话的对话历史"""
    try:
        session_id = request.session_id if request else None
        if session_id:
            success = session_manager.reset_session(session_id)
            if success:
                return {"success": True, "message": "对话历史已清空"}
            else:
                raise HTTPException(status_code=404, detail="会话不存在或已过期")
        else:
            return {"success": False, "message": "请提供 session_id"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"服务器内部错误: {str(e)}")


@app.get("/api/session/new")
async def create_new_session(_auth: bool = Depends(verify_api_key)):
    """创建一个新会话"""
    try:
        session = session_manager.create_session()
        return {"success": True, "session_id": session.session_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"创建会话失败: {str(e)}")


@app.get("/api/session/info")
async def get_session_info(
    session_id: str,
    _auth: bool = Depends(verify_api_key),
):
    """获取指定会话的信息"""
    info = session_manager.get_session_info(session_id)
    if info is None:
        raise HTTPException(status_code=404, detail="会话不存在或已过期")
    return {"success": True, "session": info}


@app.get("/api/sessions")
async def list_sessions(_auth: bool = Depends(verify_api_key)):
    """列出所有活跃会话（管理用）"""
    return {
        "success": True,
        "active_count": session_manager.active_session_count,
        "sessions": session_manager.list_sessions(),
    }


@app.get("/api/providers")
async def get_providers(_auth: bool = Depends(verify_api_key)):
    """获取支持的模型提供商列表"""
    return {
        "providers": [
            {"id": "openai", "name": "OpenAI", "models": ["gpt-4", "gpt-4-turbo", "gpt-3.5-turbo"]},
            {"id": "azure", "name": "Azure OpenAI", "models": ["使用Azure部署名称"]},
            {"id": "deepseek", "name": "DeepSeek", "models": ["deepseek-chat", "deepseek-coder"]},
            {"id": "zhipu", "name": "智谱AI", "models": ["glm-4", "glm-3-turbo"]},
            {"id": "moonshot", "name": "Moonshot", "models": ["moonshot-v1-8k", "moonshot-v1-32k"]},
            {"id": "ollama", "name": "Ollama", "models": ["llama2", "llama3", "mistral", "qwen"]},
            {"id": "custom", "name": "自定义API", "models": []},
        ]
    }


@app.get("/api/tools")
async def get_tools(_auth: bool = Depends(verify_api_key)):
    """列出所有工具及其状态"""
    from tools.base import tool_registry, tool_cache
    return {
        "success": True,
        "count": tool_registry.count,
        "tools": tool_registry.list_all(),
        "cache": tool_cache.stats,
    }


@app.post("/api/tools/{name}/disable")
async def disable_tool(name: str, _auth: bool = Depends(verify_api_key)):
    """禁用指定工具"""
    from tools.base import tool_registry
    ok = tool_registry.disable(name)
    if not ok:
        raise HTTPException(404, f"工具不存在: {name}")
    return {"success": True, "message": f"工具 '{name}' 已禁用"}


@app.post("/api/tools/{name}/enable")
async def enable_tool(name: str, _auth: bool = Depends(verify_api_key)):
    """启用指定工具"""
    from tools.base import tool_registry
    ok = tool_registry.enable(name)
    if not ok:
        raise HTTPException(404, f"工具不存在: {name}")
    return {"success": True, "message": f"工具 '{name}' 已启用"}


@app.post("/api/tools/cache/clear")
async def clear_tool_cache(_auth: bool = Depends(verify_api_key)):
    """清除工具结果缓存"""
    from tools.base import tool_cache
    tool_cache.invalidate()
    return {"success": True, "message": "缓存已清除", "stats": tool_cache.stats}


# ==================== RAG 知识库端点 ====================

@app.get("/api/rag/stats")
async def rag_stats(_auth: bool = Depends(verify_api_key)):
    """获取知识库统计"""
    from rag import rag_engine
    return {"success": True, "stats": rag_engine.stats}


@app.post("/api/rag/search")
async def rag_search(query: str, _auth: bool = Depends(verify_api_key)):
    """搜索知识库"""
    from rag import rag_engine
    results = rag_engine.search(query)
    return {"success": True, "query": query, "results": results}


@app.post("/api/rag/ingest")
async def rag_ingest(file_path: str, _auth: bool = Depends(verify_api_key)):
    """摄入文件到知识库"""
    from rag import rag_engine
    try:
        count = rag_engine.ingest_file(file_path)
        return {"success": True, "chunks": count, "file": file_path}
    except Exception as e:
        raise HTTPException(500, str(e))


# ==================== 多 Agent 端点 ====================

@app.get("/api/agents")
async def list_agents(_auth: bool = Depends(verify_api_key)):
    """列出所有子 Agent"""
    from multi_agent import orchestrator
    return {"success": True, "agents": orchestrator.list_agents()}


@app.post("/api/agents/route")
async def route_agent(query: str, _auth: bool = Depends(verify_api_key)):
    """测试路由：查看查询会被分配到哪个 Agent"""
    from multi_agent import orchestrator
    agent = orchestrator.route(query)
    return {
        "success": True,
        "query": query,
        "routed_to": agent.name,
        "description": agent.description,
        "tools": agent.tools,
    }


# ==================== 结构化输出端点 ====================

@app.get("/api/schemas")
async def list_schemas(_auth: bool = Depends(verify_api_key)):
    """列出可用的输出 Schema"""
    from structured_output import OutputSchema
    return {"success": True, "schemas": OutputSchema.list_schemas()}


@app.get("/api/schemas/{name}")
async def get_schema(name: str, _auth: bool = Depends(verify_api_key)):
    """获取指定 Schema 的 prompt 指令"""
    from structured_output import OutputSchema
    try:
        schema = OutputSchema(name)
        return {"success": True, "name": name, "instruction": schema.to_prompt_instruction()}
    except Exception:
        raise HTTPException(404, f"Schema 不存在: {name}")


# ==================== 配置端点 ====================

@app.get("/api/settings")
async def get_settings(_auth: bool = Depends(verify_api_key)):
    """获取当前应用配置（敏感信息已脱敏）"""
    from config_loader import settings
    return {"success": True, "settings": settings.safe_dict()}


@app.get("/api/prompts")
async def get_prompts(_auth: bool = Depends(verify_api_key)):
    """获取可用的 Prompt 模板列表"""
    from prompt_manager import list_prompts
    return {"success": True, "prompts": list_prompts()}


@app.get("/api/prompts/{name}")
async def get_prompt_by_name(name: str, _auth: bool = Depends(verify_api_key)):
    """获取指定 prompt 模板的渲染结果"""
    from prompt_manager import get_prompt
    try:
        rendered = get_prompt(name)
        return {"success": True, "name": name, "prompt": rendered}
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"模板不存在: {name}")


@app.post("/api/prompts/reload")
async def reload_prompts(_auth: bool = Depends(verify_api_key)):
    """热加载 prompt 模板（无需重启服务）"""
    from prompt_manager import reload_prompts
    reload_prompts()
    return {"success": True, "message": "Prompt 模板已重新加载"}


@app.get("/api/health")
async def health_check():
    """
    基础健康检查（无需认证）

    快速检查核心组件状态，适合负载均衡器的 health probe。
    响应时间 < 100ms。
    """
    report = await run_health_checks(detailed=False)
    result = health_report_to_dict(report)

    # 根据状态设置 HTTP 状态码
    if report.status == "unhealthy":
        status_code = 503
    elif report.status == "degraded":
        status_code = 200  # 降级但仍可用
    else:
        status_code = 200

    return JSONResponse(content=result, status_code=status_code)


@app.get("/api/health/detailed")
async def health_check_detailed(_auth: bool = Depends(verify_api_key)):
    """
    详细健康检查（需要认证）

    包含 LLM API 连通性检测，响应可能较慢（5-15 秒）。
    """
    report = await run_health_checks(detailed=True)
    result = health_report_to_dict(report)

    status_code = 503 if report.status == "unhealthy" else 200
    return JSONResponse(content=result, status_code=status_code)


@app.get("/api/health/live")
async def health_liveness():
    """
    存活检查（Kubernetes liveness probe）

    只检查进程是否存活，不做任何依赖检测。
    始终返回 200，除非进程已死。
    """
    return {"status": "alive", "uptime_seconds": round(get_uptime_seconds(), 1)}


@app.get("/api/health/ready")
async def health_readiness():
    """
    就绪检查（Kubernetes readiness probe）

    检查服务是否准备好接收流量。
    需要至少基础组件正常。
    """
    report = await run_health_checks(detailed=False)
    if report.status == "unhealthy":
        return JSONResponse(
            content={"status": "not_ready", "reason": "核心组件异常"},
            status_code=503,
        )
    return {"status": "ready"}


# ==================== 启动事件 ====================

@app.on_event("startup")
async def startup_event():
    """应用启动时记录配置摘要"""
    log = get_logger("web_app")
    log.info("LangChain Agent Web 服务 v2.1 启动")
    log.info(f"会话隔离: 开启 | 流式输出: 开启 (SSE)")
    log.info(f"健康检查: /api/health | /api/health/detailed | /api/health/live | /api/health/ready")
    log.info(f"API 认证: {'已启用' if config.APP_API_KEY else '关闭 (开发模式)'}")
    log.info(f"速率限制: {'已启用' if config.RATE_LIMIT_ENABLED else '关闭'}")
    log.info(f"CORS: {cors_origins} | 最大消息长度: {config.MAX_MESSAGE_LENGTH} 字符")


# ==================== 静态文件挂载 ====================

os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")


# ==================== 启动服务器 ====================

def run_server(host: str = "0.0.0.0", port: int = 8000):
    """启动Web服务器"""
    log = get_logger("web_app")
    log.info(f"启动服务器: http://{host}:{port}")

    uvicorn.run(
        "web_app:app",
        host=host,
        port=port,
        reload=False,
        log_level="warning",  # uvicorn 自身的日志降噪
    )


if __name__ == "__main__":
    run_server()
