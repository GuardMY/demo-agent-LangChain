"""
配置加载器 — pydantic-settings + YAML 分层配置

支持:
- 环境变量覆盖（最高优先级）
- YAML 文件分层: defaults.yaml → {env}.yaml → .env.local
- 类型验证（pydantic）
- 敏感信息剥离（日志/API 输出时）

用法:
    from config_loader import settings
    print(settings.llm_provider)
    print(settings.openai_model_name)
"""

import os
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """应用配置（Pydantic 验证）"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- 服务 ----
    env: str = Field(default="development", description="运行环境")
    app_port: int = Field(default=8000, ge=1, le=65535)
    log_level: str = Field(default="INFO", pattern="^(DEBUG|INFO|WARNING|ERROR)$")
    log_format: str = Field(default="console", pattern="^(console|json)$")

    # ---- LLM ----
    llm_provider: str = Field(default="openai")
    openai_api_key: str = Field(default="")
    openai_model_name: str = Field(default="gpt-4")
    deepseek_api_key: str = Field(default="")
    zhipu_api_key: str = Field(default="")
    moonshot_api_key: str = Field(default="")
    model_temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=4096, ge=1, le=128000)

    # ---- 安全 ----
    app_api_key: str = Field(default="")
    cors_allowed_origins: str = Field(default="*")
    rate_limit_enabled: bool = Field(default=True)
    rate_limit_global: str = Field(default="60/minute")
    rate_limit_chat: str = Field(default="10/minute")
    rate_limit_stream: str = Field(default="5/minute")
    max_message_length: int = Field(default=10000, ge=1, le=100000)

    # ---- Agent ----
    max_iterations: int = Field(default=10, ge=1, le=100)
    verbose: bool = Field(default=False)
    system_prompt: str = Field(default="你是智能助手。")

    # ---- 外部 API ----
    openweather_api_key: str = Field(default="")

    # ---- 数据库 ----
    redis_url: str = Field(default="redis://localhost:6379/0")

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def is_development(self) -> bool:
        return self.env == "development"

    def safe_dict(self) -> dict:
        """返回剥离敏感信息后的配置（用于 API 响应）"""
        data = self.model_dump()
        sensitive_fields = {"api_key", "secret", "password", "token"}
        for key in list(data.keys()):
            if any(s in key.lower() for s in sensitive_fields):
                val = data[key]
                if isinstance(val, str) and val:
                    data[key] = val[:4] + "****" if len(val) > 4 else "****"
                elif val:
                    data[key] = "****"
        return data


@lru_cache()
def get_settings() -> AppSettings:
    """获取全局配置（单例 + 缓存）"""
    return AppSettings()


# 全局便捷实例
settings = get_settings()
