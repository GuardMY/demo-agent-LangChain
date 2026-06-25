"""搜索工具 — 基于 DuckDuckGo 的免费网络搜索"""
from tools.base import BaseTool, ToolPermission, tool_registry


class SearchTool(BaseTool):
    name = "web_search"
    description = "网络搜索工具。当需要实时信息、新闻、百科知识时使用。输入为搜索关键词。"
    permission = ToolPermission.NETWORK
    timeout = 15.0
    cache_ttl = 120  # 搜索结果缓存 2 分钟
    tags = ["web", "search"]

    def __init__(self):
        self._search_func = None
        self._init_search()

    def _init_search(self):
        try:
            from duckduckgo_search import DDGS
            self._search_func = self._duckduckgo_search
        except ImportError:
            self._search_func = None

    def _duckduckgo_search(self, query: str) -> str:
        with __import__("duckduckgo_search").DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=5))
        if not results:
            return "未找到相关搜索结果"
        formatted = []
        for i, r in enumerate(results, 1):
            title = r.get("title", "")
            body = r.get("body", "")
            href = r.get("href", "")
            formatted.append(f"{i}. {title}\n   {body}\n   链接: {href}\n")
        return "\n".join(formatted)

    def _run(self, input_str: str) -> str:
        if self._search_func is None:
            return "搜索功能未配置，请安装: pip install duckduckgo-search"
        return self._search_func(input_str.strip())


search_tool_instance = SearchTool()
search_tool = search_tool_instance.to_langchain_tool()
tool_registry.register(search_tool_instance)
