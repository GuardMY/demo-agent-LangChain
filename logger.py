"""
结构化日志模块

特性：
- 双输出模式：开发环境彩色控制台 / 生产环境 JSON
- 请求 ID 追踪（自动注入或从 X-Request-ID 头提取）
- 分级日志：DEBUG / INFO / WARNING / ERROR
- 关键事件：LLM 调用、工具执行、会话生命周期
- 兼容标准 logging 库

用法:
    from logger import get_logger
    log = get_logger(__name__)
    log.info("用户发送消息", extra={"session_id": "abc", "message_len": 42})
"""

import json
import logging
import os
import sys
import time
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import config

# ==================== 请求级上下文 ====================

# ContextVar: 每个异步请求独立的 request_id
_request_id_var: ContextVar[str] = ContextVar("request_id", default="")
_session_id_var: ContextVar[str] = ContextVar("session_id", default="")


def set_request_id(request_id: str = None) -> str:
    """设置当前请求的 request_id"""
    rid = request_id or str(uuid.uuid4())[:8]
    _request_id_var.set(rid)
    return rid


def get_request_id() -> str:
    """获取当前请求的 request_id"""
    return _request_id_var.get()


def set_session_id(session_id: str):
    """设置当前请求的 session_id"""
    _session_id_var.set(session_id)


def get_session_id() -> str:
    """获取当前请求的 session_id"""
    return _session_id_var.get()


# ==================== JSON 格式化器 ====================

class JsonFormatter(logging.Formatter):
    """
    JSON 格式日志输出（生产环境）

    输出示例:
    {"timestamp": "2026-06-24T12:00:00.000Z", "level": "INFO",
     "logger": "web_app", "message": "请求开始", "request_id": "a1b2",
     "method": "POST", "path": "/api/chat", "status": 200, "duration_ms": 1234.5}
    """

    def format(self, record: logging.LogRecord) -> str:
        log_entry: Dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).strftime("%Y-%m-%dT%H:%M:%S.") + f"{record.msecs:03.0f}Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # 注入请求上下文
        rid = get_request_id()
        if rid:
            log_entry["request_id"] = rid
        sid = get_session_id()
        if sid:
            log_entry["session_id"] = sid[:8]

        # 注入额外字段
        if hasattr(record, "extra_fields") and record.extra_fields:
            log_entry.update(record.extra_fields)

        # 异常信息
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = {
                "type": type(record.exc_info[1]).__name__,
                "message": str(record.exc_info[1]),
            }

        return json.dumps(log_entry, ensure_ascii=False, default=str)


# ==================== 彩色控制台格式化器 ====================

class ColoredConsoleFormatter(logging.Formatter):
    """
    开发环境彩色控制台输出

    格式: HH:MM:SS LEVEL  [module]  message
    """

    COLORS = {
        "DEBUG": "\033[36m",     # 青色
        "INFO": "\033[32m",      # 绿色
        "WARNING": "\033[33m",   # 黄色
        "ERROR": "\033[31m",     # 红色
        "RESET": "\033[0m",
        "DIM": "\033[2m",
        "BOLD": "\033[1m",
    }

    def format(self, record: logging.LogRecord) -> str:
        # 时间
        timestamp = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")

        # 级别颜色
        level_color = self.COLORS.get(record.levelname, "")
        level_str = f"{level_color}{record.levelname:<7}{self.COLORS['RESET']}"

        # 模块名
        module = f"{self.COLORS['DIM']}[{record.name}]{self.COLORS['RESET']}"

        # 基础消息
        msg = record.getMessage()

        # 请求上下文
        ctx_parts = []
        rid = get_request_id()
        if rid:
            ctx_parts.append(f"req={rid}")
        sid = get_session_id()
        if sid:
            ctx_parts.append(f"ses={sid[:8]}")
        ctx = f" {self.COLORS['DIM']}({', '.join(ctx_parts)}){self.COLORS['RESET']}" if ctx_parts else ""

        # 额外字段
        extra = ""
        if hasattr(record, "extra_fields") and record.extra_fields:
            extra_parts = [f"{k}={v}" for k, v in record.extra_fields.items()
                          if k not in ("request_id", "session_id")]
            if extra_parts:
                extra = f" {self.COLORS['DIM']}| {' '.join(extra_parts)}{self.COLORS['RESET']}"

        return f"{timestamp} {level_str} {module} {msg}{ctx}{extra}"


# ==================== Logger 适配器 ====================

class StructuredLogger(logging.LoggerAdapter):
    """
    带额外字段的结构化日志适配器

    用法:
        log = get_logger(__name__)
        log.info("消息", extra={"key": "value"})
    """

    def process(self, msg, kwargs):
        extra_fields = kwargs.pop("extra", {})
        kwargs["extra"] = {"extra_fields": extra_fields}
        return msg, kwargs

    def debug(self, msg, *args, **kwargs):
        self.log(logging.DEBUG, msg, *args, **kwargs)

    def info(self, msg, *args, **kwargs):
        self.log(logging.INFO, msg, *args, **kwargs)

    def warning(self, msg, *args, **kwargs):
        self.log(logging.WARNING, msg, *args, **kwargs)

    def error(self, msg, *args, **kwargs):
        self.log(logging.ERROR, msg, *args, **kwargs)

    def exception(self, msg, *args, **kwargs):
        self.log(logging.ERROR, msg, *args, exc_info=True, **kwargs)


# ==================== 日志工厂 ====================

# 已创建的 logger 缓存（避免重复创建 handler）
_loggers: Dict[str, StructuredLogger] = {}
_initialized = False


def _init_logging():
    """初始化全局日志配置（仅执行一次）"""
    global _initialized
    if _initialized:
        return

    log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
    log_format = os.getenv("LOG_FORMAT", "console").lower()  # "console" | "json"
    log_level = getattr(logging, log_level_str, logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # 移除已有 handler（避免重复）
    root_logger.handlers.clear()

    # 创建 handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)

    if log_format == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(ColoredConsoleFormatter())

    root_logger.addHandler(handler)

    # 降低第三方库的日志噪音
    for noisy in ["uvicorn", "httpx", "openai", "urllib3", "asyncio"]:
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _initialized = True


def get_logger(name: str) -> StructuredLogger:
    """
    获取一个结构化日志器

    Args:
        name: 通常传入 __name__

    Returns:
        StructuredLogger 实例
    """
    _init_logging()

    if name in _loggers:
        return _loggers[name]

    raw_logger = logging.getLogger(name)
    logger = StructuredLogger(raw_logger, {})
    _loggers[name] = logger
    return logger


# ==================== 请求日志中间件的辅助函数 ====================

def log_request_start(method: str, path: str, client_ip: str):
    """记录 HTTP 请求开始"""
    log = get_logger("http")
    log.info(
        f"{method} {path}",
        extra={"method": method, "path": path, "client_ip": client_ip},
    )


def log_request_end(method: str, path: str, status_code: int, duration_ms: float):
    """记录 HTTP 请求结束"""
    log = get_logger("http")
    level = "WARNING" if status_code >= 400 else "INFO"
    msg = f"{method} {path} -> {status_code} ({duration_ms:.1f}ms)"
    if level == "WARNING":
        log.warning(msg, extra={"method": method, "path": path, "status": status_code, "duration_ms": round(duration_ms, 1)})
    else:
        log.info(msg, extra={"method": method, "path": path, "status": status_code, "duration_ms": round(duration_ms, 1)})


def log_llm_call(provider: str, model: str, prompt_len: int):
    """记录 LLM 调用"""
    log = get_logger("llm")
    log.info(f"LLM 调用: {provider}/{model}", extra={
        "provider": provider, "model": model, "prompt_len": prompt_len,
    })


def log_llm_result(provider: str, duration_ms: float, token_count: int = None):
    """记录 LLM 结果"""
    log = get_logger("llm")
    extra = {"provider": provider, "duration_ms": round(duration_ms, 1)}
    if token_count:
        extra["tokens"] = token_count
    log.info(f"LLM 响应: {duration_ms:.0f}ms" + (f", {token_count} tokens" if token_count else ""), extra=extra)


def log_tool_call(tool_name: str, input_preview: str):
    """记录工具调用"""
    log = get_logger("tool")
    preview = input_preview[:80] + "..." if len(input_preview) > 80 else input_preview
    log.info(f"工具: {tool_name}({preview})", extra={
        "tool": tool_name, "input_preview": preview,
    })


def log_tool_result(tool_name: str, duration_ms: float, success: bool = True):
    """记录工具结果"""
    log = get_logger("tool")
    level = "ERROR" if not success else "INFO"
    msg = f"工具结果: {tool_name} {'成功' if success else '失败'} ({duration_ms:.0f}ms)"
    if not success:
        log.error(msg, extra={"tool": tool_name, "duration_ms": round(duration_ms, 1), "success": success})
    else:
        log.info(msg, extra={"tool": tool_name, "duration_ms": round(duration_ms, 1), "success": success})


def log_session_create(session_id: str, provider: str):
    """记录会话创建"""
    log = get_logger("session")
    log.info(f"会话创建: {session_id[:8]}... ({provider})", extra={
        "session_id": session_id[:8], "provider": provider,
    })


def log_session_destroy(session_id: str):
    """记录会话销毁"""
    log = get_logger("session")
    log.info(f"会话销毁: {session_id[:8]}...", extra={"session_id": session_id[:8]})


def log_error(module: str, error: Exception, context: dict = None):
    """记录错误"""
    log = get_logger(module)
    log.error(
        f"{type(error).__name__}: {str(error)[:200]}",
        extra=context or {},
        exc_info=True,
    )
