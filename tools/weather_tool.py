"""天气查询工具 — 支持模拟数据 + 真实 API 双模式"""
import os
from tools.base import BaseTool, ToolPermission, tool_registry


class WeatherTool(BaseTool):
    name = "get_weather"
    description = "获取指定城市的当前天气。输入为城市名称（中文或英文）。"
    permission = ToolPermission.NETWORK
    timeout = 10.0
    cache_ttl = 600  # 天气缓存 10 分钟
    tags = ["weather", "query"]

    # 模拟数据（真实 API 不可用时的回退）
    MOCK_DB = {
        "北京": {"temp": 22, "condition": "多云", "humidity": 45, "wind": "东南风3级"},
        "上海": {"temp": 25, "condition": "晴", "humidity": 60, "wind": "东风2级"},
        "深圳": {"temp": 28, "condition": "阵雨", "humidity": 80, "wind": "南风3级"},
        "广州": {"temp": 27, "condition": "阴", "humidity": 70, "wind": "东南风2级"},
        "杭州": {"temp": 24, "condition": "晴", "humidity": 55, "wind": "东风1级"},
        "成都": {"temp": 20, "condition": "小雨", "humidity": 75, "wind": "北风2级"},
        "武汉": {"temp": 23, "condition": "多云", "humidity": 65, "wind": "东南风2级"},
        "西安": {"temp": 21, "condition": "晴", "humidity": 40, "wind": "东北风1级"},
        "东京": {"temp": 26, "condition": "晴", "humidity": 50, "wind": "西南风2级"},
        "纽约": {"temp": 18, "condition": "阴", "humidity": 70, "wind": "西风3级"},
        "伦敦": {"temp": 15, "condition": "小雨", "humidity": 85, "wind": "西风4级"},
        "巴黎": {"temp": 17, "condition": "晴", "humidity": 55, "wind": "西北风2级"},
    }

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("OPENWEATHER_API_KEY", "")
        self.api_mode = bool(self.api_key)

    def _query_real_api(self, city: str) -> str:
        """查询 OpenWeatherMap 真实 API"""
        import urllib.request, json
        url = (
            f"https://api.openweathermap.org/data/2.5/weather?"
            f"q={city}&appid={self.api_key}&units=metric&lang=zh_cn"
        )
        try:
            with urllib.request.urlopen(url, timeout=8) as resp:
                data = json.loads(resp.read())
            return (
                f"{data['name']}当前天气：\n"
                f"━━━━━━━━━━━━━━━\n"
                f"🌡️ 温度：{data['main']['temp']}°C（体感 {data['main']['feels_like']}°C）\n"
                f"🌤️ 天气状况：{data['weather'][0]['description']}\n"
                f"💧 湿度：{data['main']['humidity']}%\n"
                f"🌬️ 风速：{data['wind']['speed']} m/s\n"
                f"━━━━━━━━━━━━━━━\n"
                f"数据来源: OpenWeatherMap"
            )
        except Exception as e:
            return f"真实 API 查询失败 ({str(e)[:80]})，回退到模拟数据...\n{self._query_mock(city)}"

    def _query_mock(self, city: str) -> str:
        """查询模拟数据"""
        city = city.strip()
        weather = self.MOCK_DB.get(city)
        if not weather:
            for db_city, db_weather in self.MOCK_DB.items():
                if city in db_city or db_city in city:
                    weather = db_weather
                    city = db_city
                    break
        if weather:
            return (
                f"{city}当前天气：\n"
                f"━━━━━━━━━━━━━━━\n"
                f"🌡️ 温度：{weather['temp']}°C\n"
                f"🌤️ 天气状况：{weather['condition']}\n"
                f"💧 湿度：{weather['humidity']}%\n"
                f"🌬️ 风力：{weather['wind']}\n"
                f"━━━━━━━━━━━━━━━\n"
                f"⚠️ 模拟数据（设置 OPENWEATHER_API_KEY 获取真实天气）"
            )
        return f"暂未收录 '{city}' 的天气。支持城市: {', '.join(self.MOCK_DB.keys())}"

    def _run(self, city: str) -> str:
        if self.api_mode:
            return self._query_real_api(city.strip())
        return self._query_mock(city.strip())


weather_tool_instance = WeatherTool()
weather_tool = weather_tool_instance.to_langchain_tool()
tool_registry.register(weather_tool_instance)
