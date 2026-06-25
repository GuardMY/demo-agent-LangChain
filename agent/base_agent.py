"""
基础Agent模块
定义Agent的核心架构和推理逻辑
支持多种LLM提供商 + Prompt模板 + 容错重试

兼容 LangChain >= 1.0.0
"""

import asyncio
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

# ---- 兼容导入 ----
try:
    from langchain_openai import ChatOpenAI, AzureChatOpenAI
except ImportError:
    ChatOpenAI = AzureChatOpenAI = None

try:
    from langchain_community.llms import Ollama
except ImportError:
    Ollama = None

try:
    from langchain_core.messages import SystemMessage, HumanMessage
except ImportError:
    SystemMessage = HumanMessage = None

try:
    from langchain.agents import create_agent as _create_agent_lc
except ImportError:
    _create_agent_lc = None

try:
    from langchain_core.tools import Tool
except ImportError:
    Tool = None

try:
    from langgraph.checkpoint.memory import InMemorySaver
except ImportError:
    InMemorySaver = None

import config
from logger import get_logger, log_llm_call, log_tool_call
from prompt_manager import get_prompt
from resilience import RetryConfig, CircuitBreaker, create_retry_config


# ==================== LLM 工厂 ====================

class LLMFactory:
    """LLM工厂类"""

    @staticmethod
    def create_llm(provider=None, model_name=None, temperature=None, verbose=False, **kwargs):
        llm_config = config.get_llm_config(provider)
        provider = llm_config["provider"]
        temp = temperature if temperature is not None else config.MODEL_TEMPERATURE
        model = model_name or llm_config.get("model_name")

        if provider == "openai":
            return ChatOpenAI(model=model, temperature=temp, verbose=verbose,
                            openai_api_key=llm_config["api_key"],
                            openai_api_base=llm_config.get("base_url"),
                            max_tokens=config.MAX_TOKENS, streaming=True, **kwargs)
        elif provider == "azure":
            return AzureChatOpenAI(deployment_name=llm_config["deployment_name"],
                                  temperature=temp, verbose=verbose,
                                  openai_api_key=llm_config["api_key"],
                                  azure_endpoint=llm_config["azure_endpoint"],
                                  openai_api_version=llm_config["api_version"],
                                  max_tokens=config.MAX_TOKENS, streaming=True, **kwargs)
        elif provider in ["deepseek", "zhipu", "moonshot", "custom"]:
            return ChatOpenAI(model=model, temperature=temp, verbose=verbose,
                            openai_api_key=llm_config["api_key"],
                            openai_api_base=llm_config["base_url"],
                            max_tokens=config.MAX_TOKENS, streaming=True, **kwargs)
        elif provider == "ollama":
            return Ollama(model=model, temperature=temp, base_url=llm_config["base_url"], **kwargs)
        raise ValueError(f"不支持的模型提供商: {provider}")


# ==================== 基础 Agent ====================

class BaseAgent:
    """基础Agent类 — 支持 Prompt 模板 + 容错重试"""

    def __init__(self, provider=None, model_name=None, temperature=None,
                 system_prompt=None, verbose=None, max_iterations=None):
        self.provider = provider or config.LLM_PROVIDER
        self.model_name = model_name or config.MODEL_NAME or None
        self.temperature = temperature if temperature is not None else config.MODEL_TEMPERATURE
        self.verbose = verbose if verbose is not None else config.VERBOSE
        self.max_iterations = max_iterations or config.MAX_ITERATIONS

        # Prompt: 自定义字符串优先，否则使用模板
        if system_prompt and system_prompt != config.SYSTEM_PROMPT:
            self.system_prompt = system_prompt
        else:
            self.system_prompt = get_prompt("assistant")

        self.llm = None
        self.agent = None
        self.tools = []
        self.checkpointer = None

        # 容错
        self.retry_config = create_retry_config("default")
        self.circuit_breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=30)

    def _init_llm(self):
        self.llm = LLMFactory.create_llm(provider=self.provider, model_name=self.model_name,
                                         temperature=self.temperature, verbose=self.verbose)

    def _init_memory(self):
        if InMemorySaver is not None:
            self.checkpointer = InMemorySaver()

    @abstractmethod
    def _create_agent(self):
        pass

    def register_tools(self, tools):
        self.tools = tools
        if self.agent is not None:
            self._create_agent()

    def add_tool(self, tool):
        self.tools.append(tool)
        if self.agent is not None:
            self._create_agent()

    # ---- 容错: 同步重试 ----

    def _invoke_with_retry(self, query: str):
        """同步调用 Agent，指数退避重试"""
        last_error = None
        cfg = self.retry_config

        for attempt in range(cfg.max_retries + 1):
            try:
                return self.agent.invoke({"messages": [HumanMessage(content=query)]})
            except Exception as e:
                last_error = e
                msg = str(e).lower()
                # 认证错误立即抛出
                if any(kw in msg for kw in ("auth", "unauthorized", "api_key", "401", "403")):
                    raise
                if attempt == cfg.max_retries:
                    break
                delay = min(cfg.base_delay * (cfg.backoff_multiplier ** attempt), cfg.max_delay)
                if cfg.jitter:
                    delay *= 0.5 + (time.time() % 1) * 0.5
                if self.verbose:
                    log = get_logger("agent")
                    log.warning(f"LLM 重试 {attempt+1}/{cfg.max_retries+1}, {delay:.1f}s: {str(e)[:80]}")
                time.sleep(delay)

        raise last_error

    def run(self, query: str) -> str:
        """运行 Agent（同步，带重试）"""
        if self.agent is None:
            return "错误：Agent未初始化，请先调用build()方法"
        try:
            log = get_logger("agent") if self.verbose else None
            if log:
                log.info(f"处理: {query[:80]}...", extra={"query_len": len(query)})

            start = time.time()
            result = self._invoke_with_retry(query)
            duration_ms = (time.time() - start) * 1000

            if isinstance(result, dict) and "messages" in result:
                last_msg = result["messages"][-1]
                content = last_msg.content if hasattr(last_msg, "content") else str(last_msg)
            elif hasattr(result, "content"):
                content = result.content
            else:
                content = str(result)

            if log:
                log.info(f"完成 ({duration_ms:.0f}ms)", extra={"duration_ms": round(duration_ms, 1)})
            return content
        except Exception as e:
            log = get_logger("agent")
            log.error(f"处理失败（已重试{self.retry_config.max_retries}次）: {str(e)}", exc_info=True)
            return f"处理查询失败（已重试仍失败）：{str(e)}"

    # ---- 容错: 异步重试（流式） ----

    async def _ainvoke_with_retry(self, query: str):
        """异步调用 Agent，带重试"""
        last_error = None
        cfg = self.retry_config

        for attempt in range(cfg.max_retries + 1):
            try:
                return await self.agent.ainvoke({"messages": [HumanMessage(content=query)]})
            except Exception as e:
                last_error = e
                msg = str(e).lower()
                if any(kw in msg for kw in ("auth", "unauthorized", "api_key", "401", "403")):
                    raise
                if attempt == cfg.max_retries:
                    break
                delay = min(cfg.base_delay * (cfg.backoff_multiplier ** attempt), cfg.max_delay)
                if cfg.jitter:
                    delay *= 0.5 + (time.time() % 1) * 0.5
                await asyncio.sleep(delay)

        raise last_error

    async def astream(self, query: str):
        """流式运行 Agent（异步，带重试）"""
        if self.agent is None:
            yield {"type": "error", "content": "Agent未初始化"}
            return
        try:
            if hasattr(self.agent, 'astream_events'):
                async for event in self.agent.astream_events(
                    {"messages": [HumanMessage(content=query)]}, version="v2",
                ):
                    kind = event.get("event", "")
                    if kind == "on_chat_model_stream":
                        chunk = event.get("data", {}).get("chunk")
                        if chunk and hasattr(chunk, "content") and chunk.content:
                            yield {"type": "token", "content": chunk.content}
                    elif kind == "on_tool_start":
                        yield {"type": "thinking", "content": f"调用工具: {event.get('name', '?')}"}
                    elif kind == "on_tool_end":
                        output = str(event.get("data", {}).get("output", ""))[:100]
                        yield {"type": "thinking", "content": f"工具返回: {output}"}
            elif hasattr(self.agent, 'astream'):
                async for chunk in self.agent.astream({"messages": [HumanMessage(content=query)]}):
                    if isinstance(chunk, dict):
                        c = chunk.get("output") or chunk.get("text") or ""
                        if c:
                            yield {"type": "token", "content": c}
                    elif isinstance(chunk, str):
                        yield {"type": "token", "content": chunk}
            else:
                result = await self._ainvoke_with_retry(query)
                content = ""
                if isinstance(result, dict) and "messages" in result:
                    last = result["messages"][-1]
                    content = last.content if hasattr(last, "content") else str(last)
                else:
                    content = str(result)
                yield {"type": "token", "content": content}
        except Exception as e:
            yield {"type": "error", "content": f"处理失败: {str(e)}"}

    def build(self):
        self._init_llm()
        self._init_memory()
        self._create_agent()

    def reset_memory(self):
        if self.checkpointer is not None:
            self._init_memory()
            self._create_agent()


# ==================== 创建 Agent 的公共函数 ====================

def _create_agent_common(agent_instance, extra_middleware=None):
    if not agent_instance.tools:
        raise ValueError("必须先注册至少一个工具")
    if _create_agent_lc is None:
        raise RuntimeError("langchain.agents.create_agent 不可用")

    try:
        return _create_agent_lc(
            model=agent_instance.llm,
            tools=agent_instance.tools,
            system_prompt=agent_instance.system_prompt,
            checkpointer=agent_instance.checkpointer,
            middleware=extra_middleware or [],
        )
    except TypeError as e:
        raise RuntimeError(f"LangChain API 不兼容: {e}")


class ConversationalAgent(BaseAgent):
    def _create_agent(self):
        self.agent = _create_agent_common(self)


class ReActAgent(BaseAgent):
    def _create_agent(self):
        self.agent = _create_agent_common(self)


class OpenAIFunctionsAgent(BaseAgent):
    def _create_agent(self):
        self.agent = _create_agent_common(self)
