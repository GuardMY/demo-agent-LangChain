"""
工具基类模块

提供统一的工具接口，支持：
- 同步/异步双模式
- 独立超时控制
- 结果缓存（TTL）
- 权限分级
- 工具元数据

用法:
    from tools.base import BaseTool, ToolPermission, tool_cache

    class MyTool(BaseTool):
        name = "my_tool"
        description = "我的工具"
        permission = ToolPermission.READ
        timeout = 5.0

        def _run(self, input_str: str) -> str:
            return "result"

        async def _arun(self, input_str: str) -> str:
            return self._run(input_str)
"""

import asyncio
import hashlib
import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Optional


# ==================== 权限分级 ====================

class ToolPermission(Enum):
    READ = "read"            # 只读：搜索、计算、时间、天气查询
    WRITE = "write"          # 写入：文件写入
    NETWORK = "network"      # 网络：搜索 API 调用
    SYSTEM = "system"        # 系统：文件系统操作
    ADMIN = "admin"          # 管理：会话管理、配置修改


# ==================== 结果缓存 ====================

@dataclass
class CacheEntry:
    value: str
    expire_at: float


class ToolCache:
    """工具结果缓存（内存，TTL 过期）"""

    def __init__(self, max_size: int = 500):
        self._store: Dict[str, CacheEntry] = {}
        self.max_size = max_size
        self._hits = 0
        self._misses = 0

    def _make_key(self, tool_name: str, input_str: str) -> str:
        raw = f"{tool_name}:{input_str}"
        return hashlib.md5(raw.encode()).hexdigest()[:12]

    def get(self, tool_name: str, input_str: str) -> Optional[str]:
        key = self._make_key(tool_name, input_str)
        entry = self._store.get(key)
        if entry and entry.expire_at > time.time():
            self._hits += 1
            return entry.value
        if entry:
            del self._store[key]  # 过期清理
        self._misses += 1
        return None

    def set(self, tool_name: str, input_str: str, value: str, ttl_seconds: int = 300):
        key = self._make_key(tool_name, input_str)
        # 容量限制：超出时清理最旧的 20%
        if len(self._store) >= self.max_size:
            sorted_keys = sorted(self._store.keys(), key=lambda k: self._store[k].expire_at)
            for old_key in sorted_keys[: int(self.max_size * 0.2)]:
                del self._store[old_key]
        self._store[key] = CacheEntry(value=value, expire_at=time.time() + ttl_seconds)

    def invalidate(self, tool_name: str = None):
        """失效缓存"""
        if tool_name:
            prefix = hashlib.md5(f"{tool_name}:".encode()).hexdigest()[:6]
            keys = [k for k in self._store if k.startswith(prefix)]
            for k in keys:
                del self._store[k]
        else:
            self._store.clear()

    @property
    def stats(self) -> Dict[str, Any]:
        total = self._hits + self._misses
        return {
            "size": len(self._store),
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": f"{self._hits / total * 100:.1f}%" if total else "0%",
        }


# 全局缓存实例
tool_cache = ToolCache()


# ==================== 基础工具类 ====================

class BaseTool(ABC):
    """
    工具基类

    所有工具需继承此类并实现：
    - name: str         工具名称（Agent 据此选择工具）
    - description: str  工具描述（Agent 据此判断何时调用）
    - _run(input_str)   同步执行逻辑
    - _arun(input_str)  异步执行逻辑（可选，默认回退 _run）

    可选配置：
    - permission: ToolPermission  权限分级（默认 READ）
    - timeout: float             超时时间秒（默认 10.0）
    - cache_ttl: int             缓存 TTL 秒（0 表示不缓存）
    - tags: list[str]             标签（用于分组/搜索）
    """

    name: str = ""
    description: str = ""
    permission: ToolPermission = ToolPermission.READ
    timeout: float = 10.0
    cache_ttl: int = 0
    tags: list = []

    @abstractmethod
    def _run(self, input_str: str) -> str:
        """同步执行（子类必须实现）"""
        ...

    async def _arun(self, input_str: str) -> str:
        """
        异步执行（默认回退到 _run 的线程池版本）

        子类可覆盖以实现真正的异步操作（如 httpx 请求）。
        """
        return await asyncio.to_thread(self._run, input_str)

    # ---- 公共接口 ----

    def run(self, input_str: str = "") -> str:
        """
        同步执行入口（带超时 + 缓存）

        Args:
            input_str: 工具输入，默认空字符串（支持无输入工具如 datetime）
        """
        # 检查缓存
        if self.cache_ttl > 0:
            cached = tool_cache.get(self.name, input_str)
            if cached is not None:
                return cached

        try:
            result = self._run_with_timeout_sync(input_str)
        except asyncio.TimeoutError:
            return f"错误：工具 '{self.name}' 执行超时 ({self.timeout}s)"
        except Exception as e:
            return f"错误：工具 '{self.name}' 执行失败: {type(e).__name__}: {str(e)[:100]}"

        # 写入缓存
        if self.cache_ttl > 0:
            tool_cache.set(self.name, input_str, result, self.cache_ttl)

        return result

    async def arun(self, input_str: str = "") -> str:
        """
        异步执行入口（带超时 + 缓存）
        """
        if self.cache_ttl > 0:
            cached = tool_cache.get(self.name, input_str)
            if cached is not None:
                return cached

        try:
            result = await asyncio.wait_for(self._arun(input_str), timeout=self.timeout)
        except asyncio.TimeoutError:
            return f"错误：工具 '{self.name}' 执行超时 ({self.timeout}s)"
        except Exception as e:
            return f"错误：工具 '{self.name}' 执行失败: {type(e).__name__}: {str(e)[:100]}"

        if self.cache_ttl > 0:
            tool_cache.set(self.name, input_str, result, self.cache_ttl)

        return result

    def _run_with_timeout_sync(self, input_str: str) -> str:
        """同步超时包装"""
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(self._run, input_str)
            try:
                return future.result(timeout=self.timeout)
            except concurrent.futures.TimeoutError:
                raise asyncio.TimeoutError(f"工具 '{self.name}' 超时")

    @property
    def info(self) -> Dict[str, Any]:
        """工具元数据"""
        return {
            "name": self.name,
            "description": self.description[:100],
            "permission": self.permission.value,
            "timeout": self.timeout,
            "cache_ttl": self.cache_ttl,
            "tags": self.tags,
        }

    # ---- LangChain 兼容 ----

    def to_langchain_tool(self):
        """转换为 LangChain Tool 对象"""
        from langchain_core.tools import Tool
        return Tool(name=self.name, description=self.description, func=self.run)


# ==================== 工具注册表 ====================

@dataclass
class ToolEntry:
    tool: BaseTool
    enabled: bool = True
    load_time: float = field(default_factory=time.time)


class ToolRegistry:
    """
    工具注册表 — 支持热加载/卸载

    用法:
        registry = ToolRegistry()
        registry.register(my_tool)
        registry.enable("search")
        registry.disable("weather")   # 暂时禁用
        tools = registry.get_active()  # 获取可用工具列表
    """

    def __init__(self):
        self._tools: Dict[str, ToolEntry] = {}

    def register(self, tool: BaseTool) -> "ToolRegistry":
        """注册工具"""
        self._tools[tool.name] = ToolEntry(tool=tool)
        return self

    def unregister(self, name: str) -> bool:
        """卸载工具"""
        if name in self._tools:
            del self._tools[name]
            return True
        return False

    def enable(self, name: str) -> bool:
        if name in self._tools:
            self._tools[name].enabled = True
            return True
        return False

    def disable(self, name: str) -> bool:
        if name in self._tools:
            self._tools[name].enabled = False
            return True
        return False

    def get(self, name: str) -> Optional[BaseTool]:
        entry = self._tools.get(name)
        return entry.tool if entry and entry.enabled else None

    def get_active(self) -> list:
        """获取所有已启用的 LangChain Tool 对象"""
        return [e.tool.to_langchain_tool() for e in self._tools.values() if e.enabled]

    def get_active_instances(self) -> list:
        """获取所有已启用的工具实例"""
        return [e.tool for e in self._tools.values() if e.enabled]

    def list_all(self) -> list:
        """列出所有工具（含禁用）的信息"""
        return [
            {**e.tool.info, "enabled": e.enabled, "load_time": e.load_time}
            for e in self._tools.values()
        ]

    def by_permission(self, permission: ToolPermission) -> list:
        """按权限筛选工具"""
        return [e.tool for e in self._tools.values()
                if e.enabled and e.tool.permission == permission]

    def by_tag(self, tag: str) -> list:
        """按标签筛选工具"""
        return [e.tool for e in self._tools.values()
                if e.enabled and tag in e.tool.tags]

    @property
    def count(self) -> int:
        return len([e for e in self._tools.values() if e.enabled])

    @property
    def total_count(self) -> int:
        return len(self._tools)


# 全局注册表
tool_registry = ToolRegistry()
