"""日期时间工具"""
from datetime import datetime, timezone, timedelta
from tools.base import BaseTool, ToolPermission, tool_registry


class DateTimeTool(BaseTool):
    name = "get_datetime"
    description = "获取当前日期和时间。当询问时间、日期、星期时使用。"
    permission = ToolPermission.READ
    timeout = 3.0
    cache_ttl = 30  # 时间缓存 30 秒
    tags = ["time", "query"]

    def __init__(self):
        try:
            from zoneinfo import ZoneInfo
            self.timezone = ZoneInfo("Asia/Shanghai")
        except Exception:
            self.timezone = timezone(timedelta(hours=8))

    def _run(self, _input: str = "") -> str:
        now = datetime.now(self.timezone)
        weekday_names = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
        items = {
            "当前时间": now.strftime("%H:%M:%S"),
            "当前日期": now.strftime("%Y年%m月%d日"),
            "星期": weekday_names[now.weekday()],
            "时区": "Asia/Shanghai (UTC+8)",
            "完整时间戳": now.strftime("%Y-%m-%d %H:%M:%S"),
        }
        return "\n".join([f"{k}：{v}" for k, v in items.items()])


datetime_tool_instance = DateTimeTool()
datetime_tool = datetime_tool_instance.to_langchain_tool()
tool_registry.register(datetime_tool_instance)
