"""
容错与重试模块

提供生产级弹性能力：
- 指数退避重试（含随机抖动）
- 熔断器（Circuit Breaker）
- Fallback 模型链
- 超时控制

用法:
    from resilience import retry_with_backoff, CircuitBreaker, FallbackChain

    # 1. 重试装饰器
    @retry_with_backoff(max_retries=3, base_delay=1.0)
    async def call_llm(prompt): ...

    # 2. 熔断器
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=30)
    async with cb:
        result = await call_llm(prompt)

    # 3. Fallback 链
    chain = FallbackChain(["gpt-4", "gpt-3.5-turbo", "deepseek-chat"])
    result = await chain.call(lambda model: call_llm(model, prompt))
"""

import asyncio
import random
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, List, Optional

from logger import get_logger

log = get_logger(__name__)


# ==================== 重试配置 ====================

@dataclass
class RetryConfig:
    """重试策略配置"""
    max_retries: int = 3
    base_delay: float = 1.0       # 基础延迟（秒）
    max_delay: float = 30.0        # 最大延迟（秒）
    backoff_multiplier: float = 2.0  # 退避乘数
    jitter: bool = True            # 是否添加随机抖动
    retryable_exceptions: tuple = (Exception,)  # 可重试的异常类型


def _is_retryable(exception: Exception, config: RetryConfig) -> bool:
    """判断异常是否可重试"""
    # 认证错误不重试
    auth_keywords = ("auth", "unauthorized", "api_key", "credentials", "403", "401")
    msg = str(exception).lower()
    for kw in auth_keywords:
        if kw in msg:
            return False
    return isinstance(exception, config.retryable_exceptions)


async def retry_with_backoff(
    func: Callable,
    *args,
    config: RetryConfig = None,
    context: str = "",
    **kwargs,
) -> Any:
    """
    带指数退避的重试执行

    Args:
        func: 要执行的异步函数
        *args: 函数参数
        config: 重试配置
        context: 日志上下文描述
        **kwargs: 函数关键字参数

    Returns:
        函数返回值

    Raises:
        最后一次尝试的异常（重试耗尽后）
    """
    cfg = config or RetryConfig()
    last_exception = None

    for attempt in range(cfg.max_retries + 1):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            last_exception = e

            if attempt == cfg.max_retries or not _is_retryable(e, cfg):
                break

            # 计算延迟
            delay = min(cfg.base_delay * (cfg.backoff_multiplier ** attempt), cfg.max_delay)
            if cfg.jitter:
                delay = delay * (0.5 + random.random())  # 50%-100% 抖动

            log.warning(
                f"{context} 失败 (尝试 {attempt + 1}/{cfg.max_retries + 1}): "
                f"{type(e).__name__}: {str(e)[:80]} — {delay:.1f}s 后重试",
                extra={"attempt": attempt + 1, "delay": delay, "error": str(e)[:100]},
            )
            await asyncio.sleep(delay)

    log.error(f"{context} 重试耗尽 ({cfg.max_retries + 1} 次均失败): {type(last_exception).__name__}")
    raise last_exception


# ==================== 熔断器 ====================

class CircuitState(Enum):
    CLOSED = "closed"           # 正常通行
    OPEN = "open"               # 熔断开启，拒绝请求
    HALF_OPEN = "half_open"     # 半开，允许探测请求


@dataclass
class CircuitBreaker:
    """
    熔断器

    状态转换:
        CLOSED --[failure_threshold 次失败]--> OPEN
        OPEN   --[recovery_timeout 秒后]-----> HALF_OPEN
        HALF_OPEN --[成功]------------------> CLOSED
        HALF_OPEN --[失败]------------------> OPEN
    """

    failure_threshold: int = 3
    recovery_timeout: float = 30.0
    half_open_max_requests: int = 1

    _state: CircuitState = CircuitState.CLOSED
    _failure_count: int = 0
    _last_failure_time: float = 0.0
    _half_open_requests: int = 0

    def _transition_to(self, new_state: CircuitState):
        old = self._state
        self._state = new_state
        if new_state == CircuitState.OPEN:
            self._last_failure_time = time.time()
            log.warning(f"熔断器: {old.value} -> {new_state.value} (连续 {self.failure_count} 次失败)")
        elif new_state == CircuitState.CLOSED:
            self._failure_count = 0
            self._half_open_requests = 0
            log.info(f"熔断器: {old.value} -> {new_state.value} (已恢复)")

    @property
    def failure_count(self) -> int:
        return self._failure_count

    @property
    def state(self) -> CircuitState:
        # 检查 OPEN → HALF_OPEN 的自动转换
        if self._state == CircuitState.OPEN:
            if (time.time() - self._last_failure_time) >= self.recovery_timeout:
                self._transition_to(CircuitState.HALF_OPEN)
        return self._state

    @asynccontextmanager
    async def guard(self, context: str = ""):
        """
        熔断器保护上下文管理器

        async with cb.guard("LLM调用"):
            result = await call_llm()
        """
        # OPEN 状态：拒绝请求
        if self.state == CircuitState.OPEN:
            remaining = self.recovery_timeout - (time.time() - self._last_failure_time)
            raise CircuitBreakerOpenError(
                f"熔断器已开启{context}，{remaining:.0f}s 后恢复"
            )

        # HALF_OPEN 状态：限制探测请求数
        if self.state == CircuitState.HALF_OPEN:
            if self._half_open_requests >= self.half_open_max_requests:
                raise CircuitBreakerOpenError(f"熔断器半开{context}，探测请求已达上限")

        try:
            yield
        except Exception:
            self._on_failure()
            raise
        else:
            self._on_success()

    def _on_success(self):
        if self.state == CircuitState.HALF_OPEN:
            self._transition_to(CircuitState.CLOSED)
        elif self.state == CircuitState.CLOSED:
            self._failure_count = 0

    def _on_failure(self):
        self._failure_count += 1
        self._last_failure_time = time.time()
        if self.state == CircuitState.HALF_OPEN:
            self._transition_to(CircuitState.OPEN)
        elif self.state == CircuitState.CLOSED and self._failure_count >= self.failure_threshold:
            self._transition_to(CircuitState.OPEN)


class CircuitBreakerOpenError(Exception):
    """熔断器开启时抛出的异常"""
    pass


# ==================== Fallback 模型链 ====================

class FallbackChain:
    """
    Fallback 模型链

    按优先级依次尝试模型列表，某个失败后自动切换到下一个。
    所有模型都失败时抛出最后一个异常。

    用法:
        chain = FallbackChain(["gpt-4", "gpt-3.5-turbo", "deepseek-chat"])
        result = await chain.call(lambda m: agent.run_with_model(m, query))
    """

    def __init__(self, models: List[str]):
        self.models = models

    async def call(
        self,
        executor: Callable[[str], Any],
        context: str = "",
    ) -> Any:
        """
        按优先级依次尝试执行

        Args:
            executor: 接受 model_name 并返回结果的异步函数
            context: 日志上下文

        Returns:
            执行结果

        Raises:
            FallbackExhaustedError: 所有模型都失败
        """
        last_error = None

        for i, model in enumerate(self.models):
            try:
                if i > 0:
                    log.warning(f"{context}切换到备用模型: {model}", extra={"model": model, "attempt": i + 1})
                result = await executor(model)
                if i > 0:
                    log.info(f"{context}备用模型成功: {model}", extra={"model": model})
                return result
            except CircuitBreakerOpenError:
                log.warning(f"{context}模型 {model} 熔断已开启，跳过", extra={"model": model})
                last_error = CircuitBreakerOpenError(f"所有模型均被熔断{context}")
            except Exception as e:
                last_error = e
                log.warning(f"{context}模型 {model} 失败: {type(e).__name__}")

        raise FallbackExhaustedError(
            f"{context}所有 {len(self.models)} 个模型均失败。最后错误: {type(last_error).__name__}: {str(last_error)[:100]}"
        )


class FallbackExhaustedError(Exception):
    """所有 Fallback 模型都失败时抛出"""
    pass


# ==================== 重试策略工厂 ====================

def create_retry_config(strategy: str = "default") -> RetryConfig:
    """
    创建预设重试策略

    Args:
        strategy: "default" | "fast" | "persistent" | "gentle"

    Returns:
        RetryConfig
    """
    presets = {
        "default": RetryConfig(max_retries=3, base_delay=1.0, max_delay=30.0),
        "fast": RetryConfig(max_retries=2, base_delay=0.3, max_delay=5.0),
        "persistent": RetryConfig(max_retries=5, base_delay=2.0, max_delay=60.0),
        "gentle": RetryConfig(max_retries=3, base_delay=2.0, max_delay=30.0, jitter=True),
    }
    return presets.get(strategy, presets["default"])


# ==================== 超时控制 ====================

async def with_timeout(coro, timeout_seconds: float, context: str = ""):
    """
    为异步操作添加超时

    Args:
        coro: 协程
        timeout_seconds: 超时时间（秒）
        context: 日志上下文

    Returns:
        协程结果

    Raises:
        asyncio.TimeoutError: 超时
    """
    try:
        return await asyncio.wait_for(coro, timeout=timeout_seconds)
    except asyncio.TimeoutError:
        log.error(f"{context}操作超时 ({timeout_seconds}s)")
        raise
