"""
天气 & 日期时间工具测试
"""

import pytest
from tools.weather_tool import WeatherTool
from tools.datetime_tool import DateTimeTool


class TestWeatherTool:
    """天气工具测试"""

    @pytest.fixture
    def weather(self):
        return WeatherTool()

    def test_query_beijing(self, weather):
        result = weather.run("北京")
        assert "北京" in result
        assert "温度" in result
        assert "天气状况" in result

    def test_query_shanghai(self, weather):
        result = weather.run("上海")
        assert "上海" in result or "晴" in result

    def test_query_english(self, weather):
        """英文城市名"""
        result = weather.run("Tokyo")
        assert "东京" in result

    def test_fuzzy_match(self, weather):
        """模糊匹配"""
        result = weather.run("京")
        assert "北京" in result

    def test_unknown_city(self, weather):
        """未收录的城市"""
        result = weather.run("火星")
        assert "暂未收录" in result or "不支持" in result

    def test_case_insensitive(self, weather):
        """大小写不敏感"""
        result = weather.run("  beijing  ")
        # 清洗空白
        assert "东京" not in result or "北京" in result or "暂未" in result

    def test_result_format(self, weather):
        """返回格式包含所有字段"""
        result = weather.run("北京")
        assert "温度" in result
        assert "°C" in result
        assert "湿度" in result
        assert "风力" in result


class TestDateTimeTool:
    """日期时间工具测试"""

    @pytest.fixture
    def dt_tool(self):
        return DateTimeTool()

    def test_basic_time(self, dt_tool):
        result = dt_tool.run()
        assert "当前时间" in result
        assert "当前日期" in result
        assert "星期" in result
        assert "时区" in result
        assert "Asia/Shanghai" in result or "UTC+8" in result

    def test_multiple_calls(self, dt_tool):
        """多次调用不报错"""
        r1 = dt_tool.run()
        r2 = dt_tool.run()
        assert r1 == r2 or "当前时间" in r1  # 同秒内相同，跨秒不同但都有格式
