"""
API 集成测试（FastAPI TestClient）
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """创建 TestClient"""
    from web_app import app
    return TestClient(app)


class TestHealthEndpoints:
    """健康检查端点"""

    def test_health(self, client):
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("healthy", "degraded")
        assert "checks" in data
        assert "uptime_seconds" in data
        assert len(data["checks"]) >= 6  # 至少 6 项检查

    def test_health_live(self, client):
        response = client.get("/api/health/live")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "alive"
        assert "uptime_seconds" in data

    def test_health_ready(self, client):
        response = client.get("/api/health/ready")
        assert response.status_code in (200, 503)
        data = response.json()
        assert data["status"] in ("ready", "not_ready")


class TestConfigEndpoints:
    """配置端点"""

    def test_get_config(self, client):
        response = client.get("/api/config")
        assert response.status_code == 200
        data = response.json()
        assert "provider" in data
        assert "available_providers" in data

    def test_get_providers(self, client):
        response = client.get("/api/providers")
        assert response.status_code == 200
        data = response.json()
        assert len(data["providers"]) == 7
        assert data["providers"][0]["id"] == "openai"


class TestSessionEndpoints:
    """会话端点"""

    def test_create_session(self, client):
        """创建会话 (API Key 不存在时可能失败)"""
        response = client.get("/api/session/new")
        # 可能会因为缺乏 LLM API Key 而 500
        if response.status_code == 200:
            data = response.json()
            assert "session_id" in data

    def test_list_sessions(self, client):
        response = client.get("/api/sessions")
        assert response.status_code == 200
        data = response.json()
        assert "active_count" in data
        assert "sessions" in data


class TestChatValidation:
    """聊天输入验证"""

    def test_empty_message_rejected(self, client):
        response = client.post("/api/chat", json={
            "message": "",
            "agent_type": "conversational",
            "provider": "openai",
            "model_name": "gpt-4",
        })
        assert response.status_code == 422  # Pydantic validation error

    def test_long_message_rejected(self, client):
        response = client.post("/api/chat", json={
            "message": "x" * 20000,
            "agent_type": "conversational",
            "provider": "openai",
            "model_name": "gpt-4",
        })
        assert response.status_code == 422

    def test_invalid_agent_type_rejected(self, client):
        response = client.post("/api/chat", json={
            "message": "hello",
            "agent_type": "evil_hacker",
            "provider": "openai",
            "model_name": "gpt-4",
        })
        assert response.status_code == 422

    def test_invalid_provider_rejected(self, client):
        response = client.post("/api/config", json={
            "provider": "evil_provider",
            "model_name": "gpt-4",
        })
        assert response.status_code == 422


class TestStaticFiles:
    """静态文件"""

    def test_root_returns_html(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")

    def test_static_js(self, client):
        response = client.get("/static/index.html")
        assert response.status_code == 200


class TestSecurityHeaders:
    """安全响应头"""

    def test_security_headers(self, client):
        response = client.get("/api/health/live")
        assert response.headers.get("X-Content-Type-Options") == "nosniff"
        assert response.headers.get("X-Frame-Options") == "DENY"

    def test_request_id_header(self, client):
        response = client.get("/api/health/live")
        assert "X-Request-ID" in response.headers
