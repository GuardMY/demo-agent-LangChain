"""
CI 冒烟测试 — 日志模块
"""

import json
import logging
import os

import pytest


class TestLogger:
    """日志模块测试"""

    def test_get_logger(self):
        """获取 logger 实例"""
        from logger import get_logger
        log = get_logger("test_logger")
        assert log is not None

    def test_logger_output(self):
        """日志输出不抛异常"""
        from logger import get_logger
        log = get_logger("test_output")
        log.info("测试消息")
        log.warning("测试警告")
        log.error("测试错误")

    def test_extra_fields(self):
        """额外字段记录"""
        from logger import get_logger
        log = get_logger("test_extra")
        log.info("带字段", extra={"key": "value", "count": 1})

    def test_request_context(self):
        """请求上下文注入"""
        from logger import set_request_id, set_session_id, get_request_id, get_session_id

        set_request_id("test-req-001")
        set_session_id("test-sess-001")

        assert get_request_id() == "test-req-001"
        assert get_session_id() == "test-sess-001"

    def test_json_formatter(self):
        """JSON 格式化器"""
        from logger import JsonFormatter, set_request_id

        set_request_id("fmt-test")
        formatter = JsonFormatter()
        record = logging.LogRecord(
            "test", logging.INFO, "", 0, "test message", None, None
        )
        record.extra_fields = {"method": "GET", "status": 200}

        output = formatter.format(record)
        parsed = json.loads(output)

        assert parsed["level"] == "INFO"
        assert parsed["message"] == "test message"
        assert parsed["method"] == "GET"
        assert parsed["status"] == 200
        assert parsed["request_id"] == "fmt-test"

    def test_colored_formatter(self):
        """彩色控制台格式化器"""
        from logger import ColoredConsoleFormatter

        formatter = ColoredConsoleFormatter()
        record = logging.LogRecord(
            "test", logging.INFO, "", 0, "test message", None, None
        )
        record.extra_fields = {}
        output = formatter.format(record)
        assert "test message" in output
        assert "INFO" in output
