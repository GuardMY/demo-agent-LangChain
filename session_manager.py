"""
会话管理模块
管理多用户会话隔离，每个会话拥有独立的 Agent 实例和对话记忆

功能：
- 创建/销毁会话
- 会话级别的 Agent 隔离（每个会话独立的 LLM + Memory + Tools）
- 会话 TTL 自动过期清理
- 并发安全（线程锁）
"""

import asyncio
import threading
import time
import uuid
from typing import Dict, Optional, Tuple

from logger import get_logger, log_session_create, log_session_destroy

from agent.base_agent import (
    BaseAgent,
    ConversationalAgent,
    ReActAgent,
    OpenAIFunctionsAgent,
)
from tools.base import tool_registry

# 导入工具模块（触发注册到 tool_registry）
import tools.search_tool      # noqa
import tools.calculator_tool  # noqa
import tools.weather_tool     # noqa
import tools.datetime_tool    # noqa
import tools.file_tool        # noqa

import config


# ==================== 会话数据模型 ====================

class Session:
    """
    单个会话实例

    封装一个独立的 Agent 及其相关状态
    """

    def __init__(
        self,
        session_id: str,
        provider: str,
        model_name: str,
        agent_type: str,
        prompt_name: str = "assistant",
    ):
        self.session_id = session_id
        self.provider = provider
        self.model_name = model_name
        self.agent_type = agent_type
        self.prompt_name = prompt_name
        self.agent: Optional[BaseAgent] = None
        self.created_at = time.time()
        self.last_access = time.time()

        # 从注册表获取所有活跃工具
        self._tools = tool_registry.get_active()

        self._build_agent()

    def _build_agent(self):
        """构建 Agent 实例"""
        if self.agent_type == "react":
            self.agent = ReActAgent(
                provider=self.provider,
                model_name=self.model_name,
                system_prompt=None,  # 使用模板
            )
        elif self.agent_type == "functions":
            self.agent = OpenAIFunctionsAgent(
                provider=self.provider,
                model_name=self.model_name,
                system_prompt=None,
            )
        else:
            self.agent = ConversationalAgent(
                provider=self.provider,
                model_name=self.model_name,
                system_prompt=None,
            )

        self.agent.register_tools(self._tools)
        self.agent.build()

    def chat(self, message: str) -> str:
        """处理聊天消息（同步）"""
        self.last_access = time.time()
        if self.agent is None:
            return "错误：会话未正确初始化"
        return self.agent.run(message)

    async def achat(self, message: str) -> str:
        """
        处理聊天消息（异步，不阻塞事件循环）

        将同步的 Agent.run() 放入线程池执行，
        避免阻塞 FastAPI 的 async event loop。
        """
        self.last_access = time.time()
        if self.agent is None:
            return "错误：会话未正确初始化"
        return await asyncio.to_thread(self.agent.run, message)

    async def astream(self, message: str):
        """
        处理聊天消息（流式）

        使用 Agent 的 astream 方法，逐 token 推送响应。

        Args:
            message: 用户消息

        Yields:
            dict: 流式事件
        """
        self.last_access = time.time()
        if self.agent is None:
            yield {"type": "error", "content": "错误：会话未正确初始化"}
            return

        async for event in self.agent.astream(message):
            yield event

    def reset_memory(self):
        """重置对话记忆"""
        self.last_access = time.time()
        if self.agent:
            self.agent.reset_memory()

    def is_expired(self, ttl_seconds: int) -> bool:
        """检查会话是否过期"""
        return (time.time() - self.last_access) > ttl_seconds


# ==================== 会话管理器 ====================

class SessionManager:
    """
    会话管理器

    负责创建、查找、销毁会话，以及过期会话的自动清理

    使用示例:
        manager = SessionManager(ttl_seconds=3600)
        session = manager.create_session("openai", "gpt-4", "conversational")
        response = manager.chat(session.session_id, "你好")
        manager.destroy_session(session.session_id)
    """

    def __init__(self, ttl_seconds: int = 3600):
        """
        初始化会话管理器

        Args:
            ttl_seconds: 会话过期时间（秒），默认 1 小时
        """
        self._sessions: Dict[str, Session] = {}
        self._lock = threading.Lock()
        self.ttl_seconds = ttl_seconds

    def create_session(
        self,
        provider: str = None,
        model_name: str = None,
        agent_type: str = "conversational",
        prompt_name: str = "assistant",
    ) -> Session:
        """
        创建新会话

        Args:
            provider: 模型提供商
            model_name: 模型名称
            agent_type: Agent 类型

        Returns:
            Session: 新创建的会话实例
        """
        # 自动清理过期会话
        self._cleanup_expired()

        session_id = str(uuid.uuid4())
        provider = provider or config.LLM_PROVIDER
        model_name = model_name or None

        with self._lock:
            session = Session(
                session_id=session_id,
                provider=provider,
                model_name=model_name,
                agent_type=agent_type,
                prompt_name=prompt_name,
            )
            self._sessions[session_id] = session

        log = get_logger("session_manager")
        log.info(f"会话创建: {session_id[:8]}... ({provider})",
                 extra={"session_id": session_id[:8], "provider": provider,
                        "active_count": len(self._sessions)})

        return session

    def get_session(self, session_id: str) -> Optional[Session]:
        """
        获取会话

        Args:
            session_id: 会话 ID

        Returns:
            Session 或 None
        """
        session = self._sessions.get(session_id)
        if session is None:
            return None

        # 检查是否过期
        if session.is_expired(self.ttl_seconds):
            self.destroy_session(session_id)
            return None

        return session

    def get_or_create_session(
        self,
        session_id: str = None,
        provider: str = None,
        model_name: str = None,
        agent_type: str = "conversational",
    ) -> Tuple[Session, bool]:
        """
        获取已有会话，或创建新会话

        Args:
            session_id: 会话 ID（可选，为 None 则创建新会话）
            provider: 模型提供商（创建时使用）
            model_name: 模型名称（创建时使用）
            agent_type: Agent 类型（创建时使用）

        Returns:
            Tuple[Session, bool]: (会话实例, 是否为新创建)
        """
        if session_id:
            session = self.get_session(session_id)
            if session:
                return session, False

        # 创建新会话
        session = self.create_session(
            provider=provider,
            model_name=model_name,
            agent_type=agent_type,
        )
        return session, True

    def chat(self, session_id: str, message: str) -> str:
        """
        通过会话处理聊天消息（同步）

        Args:
            session_id: 会话 ID
            message: 用户消息

        Returns:
            str: Agent 响应
        """
        session = self.get_session(session_id)
        if session is None:
            return "错误：会话不存在或已过期，请刷新页面重新开始"
        return session.chat(message)

    async def achat(self, session_id: str, message: str) -> str:
        """
        通过会话处理聊天消息（异步，不阻塞事件循环）
        """
        session = self.get_session(session_id)
        if session is None:
            return "错误：会话不存在或已过期，请刷新页面重新开始"
        return await session.achat(message)

    def reset_session(self, session_id: str) -> bool:
        """
        重置会话记忆

        Args:
            session_id: 会话 ID

        Returns:
            bool: 是否成功
        """
        session = self.get_session(session_id)
        if session is None:
            return False
        session.reset_memory()
        return True

    def destroy_session(self, session_id: str):
        """
        销毁会话

        Args:
            session_id: 会话 ID
        """
        with self._lock:
            existed = self._sessions.pop(session_id, None)
        if existed:
            log = get_logger("session_manager")
            log.info(f"会话销毁: {session_id[:8]}...",
                     extra={"session_id": session_id[:8], "active_count": len(self._sessions)})

    def _cleanup_expired(self):
        """清理所有过期会话"""
        with self._lock:
            expired_ids = [
                sid for sid, session in self._sessions.items()
                if session.is_expired(self.ttl_seconds)
            ]
            for sid in expired_ids:
                del self._sessions[sid]

    @property
    def active_session_count(self) -> int:
        """获取活跃会话数"""
        self._cleanup_expired()
        return len(self._sessions)

    def get_session_info(self, session_id: str) -> Optional[dict]:
        """
        获取会话信息（不含敏感数据）

        Args:
            session_id: 会话 ID

        Returns:
            dict: 会话信息
        """
        session = self.get_session(session_id)
        if session is None:
            return None

        return {
            "session_id": session.session_id,
            "provider": session.provider,
            "model_name": session.model_name,
            "agent_type": session.agent_type,
            "created_at": session.created_at,
            "last_access": session.last_access,
        }

    def list_sessions(self) -> list:
        """列出所有活跃会话的信息"""
        self._cleanup_expired()
        return [
            {
                "session_id": s.session_id,
                "provider": s.provider,
                "model_name": s.model_name,
                "agent_type": s.agent_type,
                "created_at": s.created_at,
            }
            for s in self._sessions.values()
        ]


# ==================== 全局会话管理器 ====================

# 默认 TTL: 1 小时
session_manager = SessionManager(ttl_seconds=3600)
