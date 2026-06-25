"""
配置模块 - 集中管理项目配置
包含API密钥、模型参数、工具配置等
支持多种LLM提供商：OpenAI、Azure OpenAI、本地模型等
"""

import os
from pathlib import Path
from typing import Literal

# ==================== 项目路径配置 ====================
# 获取项目根目录的绝对路径
BASE_DIR = Path(__file__).resolve().parent

# ==================== 模型提供商配置 ====================
# 支持的模型提供商类型
# - openai: OpenAI官方API (GPT-3.5, GPT-4等)
# - azure: Azure OpenAI服务
# - deepseek: DeepSeek API (兼容OpenAI格式)
# - zhipu: 智谱AI (GLM系列模型)
# - moonshot: Moonshot AI (Kimi)
# - ollama: 本地Ollama服务
# - custom: 自定义OpenAI兼容API
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")

# ==================== OpenAI 配置 ====================
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_API_BASE = os.getenv("OPENAI_API_BASE", "")  # 可选，用于代理或自定义端点
OPENAI_MODEL_NAME = os.getenv("OPENAI_MODEL_NAME", "gpt-4")

# ==================== Azure OpenAI 配置 ====================
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "")  # 如: https://your-resource.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME", "")  # Azure部署名称
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")

# ==================== DeepSeek 配置 ====================
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_BASE = os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com/v1")
DEEPSEEK_MODEL_NAME = os.getenv("DEEPSEEK_MODEL_NAME", "deepseek-chat")

# ==================== 智谱AI 配置 ====================
ZHIPU_API_KEY = os.getenv("ZHIPU_API_KEY", "")
ZHIPU_API_BASE = os.getenv("ZHIPU_API_BASE", "https://open.bigmodel.cn/api/paas/v4")
ZHIPU_MODEL_NAME = os.getenv("ZHIPU_MODEL_NAME", "glm-4")

# ==================== Moonshot (Kimi) 配置 ====================
MOONSHOT_API_KEY = os.getenv("MOONSHOT_API_KEY", "")
MOONSHOT_API_BASE = os.getenv("MOONSHOT_API_BASE", "https://api.moonshot.cn/v1")
MOONSHOT_MODEL_NAME = os.getenv("MOONSHOT_MODEL_NAME", "moonshot-v1-8k")

# ==================== Ollama (本地模型) 配置 ====================
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL_NAME = os.getenv("OLLAMA_MODEL_NAME", "llama2")

# ==================== 自定义OpenAI兼容API配置 ====================
CUSTOM_API_KEY = os.getenv("CUSTOM_API_KEY", "")
CUSTOM_API_BASE = os.getenv("CUSTOM_API_BASE", "")
CUSTOM_MODEL_NAME = os.getenv("CUSTOM_MODEL_NAME", "")

# ==================== 通用模型配置 ====================
# 默认模型名称（根据提供商自动选择）
MODEL_NAME = os.getenv("MODEL_NAME", "")  # 留空则使用提供商默认模型

# 模型温度参数：控制输出的随机性
# 范围0-1，值越高越有创造性，值越低越确定
MODEL_TEMPERATURE = float(os.getenv("MODEL_TEMPERATURE", "0.7"))

# 最大token数限制
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "4096"))

# ==================== 工具配置 ====================
# 搜索工具配置
SEARCH_API_KEY = os.getenv("SEARCH_API_KEY", "")  # 搜索API密钥

# 计算器工具精度配置
CALCULATOR_PRECISION = 10  # 计算结果保留的小数位数

# ==================== Agent配置 ====================
# Agent行为配置
MAX_ITERATIONS = 10  # Agent最大思考迭代次数，防止无限循环
VERBOSE = True  # 是否打印详细执行过程

# ==================== 安全配置 ====================
# 应用 API Key（留空则不启用认证）
APP_API_KEY = os.getenv("APP_API_KEY", "")

# CORS 允许的域名白名单（逗号分隔，* 表示全部允许）
CORS_ALLOWED_ORIGINS = os.getenv("CORS_ALLOWED_ORIGINS", "*").split(",")

# 请求频率限制
RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "true").lower() == "true"
RATE_LIMIT_GLOBAL = os.getenv("RATE_LIMIT_GLOBAL", "60/minute")       # 全局限流
RATE_LIMIT_CHAT = os.getenv("RATE_LIMIT_CHAT", "10/minute")           # 聊天端点的限流
RATE_LIMIT_STREAM = os.getenv("RATE_LIMIT_STREAM", "5/minute")        # 流式端点的限流

# 输入验证
MAX_MESSAGE_LENGTH = int(os.getenv("MAX_MESSAGE_LENGTH", "10000"))    # 最大消息长度（字符）
MAX_REQUEST_BODY_SIZE = int(os.getenv("MAX_REQUEST_BODY_SIZE", str(1024 * 1024)))  # 最大请求体（默认 1MB）

# ==================== 系统提示配置 ====================
# 定义Agent的系统提示词，影响Agent的行为和角色设定
SYSTEM_PROMPT = """你是一个智能助手，由LangChain驱动的Agent。
你可以通过使用各种工具来回答用户的问题。
请始终尽力完成用户的请求，并在无法完成时给出清晰的解释。"""


# ==================== 模型配置工厂函数 ====================
def get_llm_config(provider: str = None) -> dict:
    """
    根据提供商获取LLM配置
    
    Args:
        provider: 模型提供商，如果为None则使用LLM_PROVIDER环境变量
        
    Returns:
        dict: 包含模型配置的字典，可直接传给LLM构造函数
    """
    provider = provider or LLM_PROVIDER
    provider = provider.lower()
    
    if provider == "openai":
        return {
            "provider": "openai",
            "api_key": OPENAI_API_KEY,
            "base_url": OPENAI_API_BASE or None,
            "model_name": MODEL_NAME or OPENAI_MODEL_NAME,
        }
    
    elif provider == "azure":
        return {
            "provider": "azure",
            "api_key": AZURE_OPENAI_API_KEY,
            "azure_endpoint": AZURE_OPENAI_ENDPOINT,
            "api_version": AZURE_OPENAI_API_VERSION,
            "deployment_name": AZURE_OPENAI_DEPLOYMENT_NAME,
            "model_name": MODEL_NAME or AZURE_OPENAI_DEPLOYMENT_NAME,
        }
    
    elif provider == "deepseek":
        return {
            "provider": "deepseek",
            "api_key": DEEPSEEK_API_KEY,
            "base_url": DEEPSEEK_API_BASE,
            "model_name": MODEL_NAME or DEEPSEEK_MODEL_NAME,
        }
    
    elif provider == "zhipu":
        return {
            "provider": "zhipu",
            "api_key": ZHIPU_API_KEY,
            "base_url": ZHIPU_API_BASE,
            "model_name": MODEL_NAME or ZHIPU_MODEL_NAME,
        }
    
    elif provider == "moonshot":
        return {
            "provider": "moonshot",
            "api_key": MOONSHOT_API_KEY,
            "base_url": MOONSHOT_API_BASE,
            "model_name": MODEL_NAME or MOONSHOT_MODEL_NAME,
        }
    
    elif provider == "ollama":
        return {
            "provider": "ollama",
            "base_url": OLLAMA_BASE_URL,
            "model_name": MODEL_NAME or OLLAMA_MODEL_NAME,
        }
    
    elif provider == "custom":
        return {
            "provider": "custom",
            "api_key": CUSTOM_API_KEY,
            "base_url": CUSTOM_API_BASE,
            "model_name": MODEL_NAME or CUSTOM_MODEL_NAME,
        }
    
    else:
        raise ValueError(f"不支持的模型提供商: {provider}。支持的提供商: openai, azure, deepseek, zhipu, moonshot, ollama, custom")