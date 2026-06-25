"""
多 Agent 协作模块

架构:
    Supervisor Agent (调度者)
    ├── Search Agent (搜索专家)
    ├── Coder Agent (代码专家)
    ├── Analyst Agent (数据分析专家)
    └── General Agent (通用助手 — 默认路由)

用法:
    from multi_agent import MultiAgentOrchestrator
    orch = MultiAgentOrchestrator()
    result = await orch.route("帮我搜索最新AI新闻并总结")

配置:
    设置 OPENAI_API_KEY 环境变量
"""

import asyncio
from dataclasses import dataclass
from typing import Dict, List, Optional

from logger import get_logger

log = get_logger(__name__)


# ==================== 子 Agent 定义 ====================

@dataclass
class SubAgent:
    """子 Agent 描述"""
    name: str
    description: str
    system_prompt: str
    tools: List[str]  # 工具名称列表
    keywords: List[str]  # 触发关键词


# 默认子 Agent 配置
DEFAULT_SUB_AGENTS = [
    SubAgent(
        name="searcher",
        description="网络搜索专家，擅长搜索最新信息、新闻、百科知识",
        system_prompt="你是搜索专家。对用户的查询，使用 web_search 工具搜索相关最新信息，然后整理成清晰的中文回答。",
        tools=["web_search"],
        keywords=["搜索", "搜索", "新闻", "最新", "百科", "什么是", "查一下", "介绍"],
    ),
    SubAgent(
        name="coder",
        description="编程专家，擅长编写代码、调试、算法设计",
        system_prompt="你是编程专家。使用 calculator 进行计算，使用 file_operations 读写代码文件。给出清晰的代码解释。",
        tools=["calculator", "file_operations"],
        keywords=["代码", "编程", "python", "算法", "函数", "debug", "bug", "写一个", "实现"],
    ),
    SubAgent(
        name="analyst",
        description="数据分析专家，擅长计算、统计和数据分析",
        system_prompt="你是数据分析专家。使用 calculator 进行精确计算，使用 web_search 获取数据。用数据说话，给出具体数字。",
        tools=["calculator", "web_search"],
        keywords=["计算", "统计", "数据", "分析", "对比", "比例", "百分比", "趋势"],
    ),
    SubAgent(
        name="general",
        description="通用助手，处理日常对话和未分类的请求",
        system_prompt="你是通用智能助手。使用合适的工具回答用户的各种问题。中文优先，回答简洁清晰。",
        tools=["calculator", "web_search", "get_weather", "get_datetime", "file_operations"],
        keywords=[],  # 兜底路由
    ),
]


# ==================== 调度器 ====================

class MultiAgentOrchestrator:
    """
    多 Agent 调度器

    根据用户输入的关键词匹配最合适的子 Agent，
    然后使用该 Agent 的配置处理请求。
    """

    def __init__(self, sub_agents: List[SubAgent] = None):
        self.sub_agents = sub_agents or DEFAULT_SUB_AGENTS
        log.info(f"多 Agent 调度器初始化: {len(self.sub_agents)} 个子 Agent")

    def route(self, query: str) -> SubAgent:
        """
        根据查询内容路由到最合适的子 Agent

        匹配规则：关键词匹配 → 得分最高的 Agent。
        无匹配时返回 general Agent。
        """
        query_lower = query.lower()
        best_agent = self.sub_agents[-1]  # general
        best_score = 0

        for agent in self.sub_agents[:-1]:
            score = sum(1 for kw in agent.keywords if kw.lower() in query_lower)
            if score > best_score:
                best_score = score
                best_agent = agent

        return best_agent

    def get_tools_for(self, agent_name: str) -> List[str]:
        """获取指定 Agent 需要的工具名称列表"""
        for a in self.sub_agents:
            if a.name == agent_name:
                return a.tools
        return []

    def list_agents(self) -> List[dict]:
        """列出所有子 Agent"""
        return [
            {
                "name": a.name,
                "description": a.description,
                "keywords": a.keywords[:5],
                "tools": a.tools,
            }
            for a in self.sub_agents
        ]

    def get_agent(self, name: str) -> Optional[SubAgent]:
        for a in self.sub_agents:
            if a.name == name:
                return a
        return None


# 全局实例
orchestrator = MultiAgentOrchestrator()
