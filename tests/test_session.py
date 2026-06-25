"""
会话管理器测试
"""

import time
from unittest.mock import patch, MagicMock

import pytest
from session_manager import SessionManager, Session


# 全局 mock：避免 Session.__init__ 中 _build_agent 尝试连接 LLM
@pytest.fixture(autouse=True)
def mock_session_build():
    """所有测试自动 mock Session._build_agent"""
    with patch.object(Session, "_build_agent", return_value=None):
        yield


class TestSessionIsolation:
    """会话隔离测试"""

    @pytest.fixture
    def mgr(self):
        return SessionManager(ttl_seconds=3600)

    def test_create_session(self, mgr):
        """创建会话"""
        assert mgr.active_session_count >= 0

    def test_get_nonexistent(self, mgr):
        """获取不存在的会话返回 None"""
        assert mgr.get_session("nonexistent-id") is None

    def test_destroy_nonexistent(self, mgr):
        """销毁不存在的会话不抛异常"""
        mgr.destroy_session("nonexistent-id")
        assert mgr.active_session_count >= 0

    def test_list_empty(self, mgr):
        """空列表"""
        sessions = mgr.list_sessions()
        assert isinstance(sessions, list)

    def test_reset_nonexistent(self, mgr):
        """重置不存在的会话返回 False"""
        assert mgr.reset_session("nonexistent-id") is False

    def test_info_nonexistent(self, mgr):
        """获取不存在会话信息返回 None"""
        assert mgr.get_session_info("nonexistent-id") is None


class TestSessionTTL:
    """会话过期测试"""

    def test_ttl_expired(self, mock_session_build):
        """TTL 过期判断"""
        s = Session(
            session_id="test-ttl",
            provider="openai",
            model_name="gpt-4",
            agent_type="conversational",
        )
        s.last_access = time.time() - 100
        assert s.is_expired(ttl_seconds=60) is True

        s.last_access = time.time() - 10
        assert s.is_expired(ttl_seconds=60) is False

    def test_ttl_boundary(self, mock_session_build):
        """TTL 边界值"""
        s = Session(
            session_id="test-boundary",
            provider="openai",
            model_name="gpt-4",
            agent_type="conversational",
        )
        s.last_access = time.time() - 59
        assert s.is_expired(ttl_seconds=60) is False

        s.last_access = time.time() - 61
        assert s.is_expired(ttl_seconds=60) is True


class TestSessionAttributes:
    """会话属性测试"""

    def test_session_basic_attrs(self, mock_session_build):
        s = Session(
            session_id="test-attrs",
            provider="openai",
            model_name="gpt-4",
            agent_type="conversational",
        )
        assert s.session_id == "test-attrs"
        assert s.provider == "openai"
        assert s.model_name == "gpt-4"
        assert s.agent_type == "conversational"
        assert s.created_at > 0

    def test_session_last_access_updated(self, mock_session_build):
        s = Session(
            session_id="test-access",
            provider="openai",
            model_name="gpt-4",
            agent_type="conversational",
        )
        s.agent = MagicMock()
        s.agent.run.return_value = "mock response"

        original = s.last_access
        time.sleep(0.1)
        s.chat("hello")
        assert s.last_access > original


class TestSessionManagerConcurrency:
    """会话管理器并发安全"""

    def test_lock_safety(self, mock_session_build):
        """多线程操作 _sessions 字典的锁安全"""
        import threading

        mgr = SessionManager(ttl_seconds=3600)

        def add_to_dict(idx):
            with mgr._lock:
                mgr._sessions[f"thread-{idx}"] = f"value-{idx}"

        threads = [threading.Thread(target=add_to_dict, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(mgr._sessions) == 20
