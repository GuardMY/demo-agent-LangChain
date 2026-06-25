"""
LangChain Agent 演示程序

支持两种运行模式：
1. Web模式 - 通过浏览器交互（默认）
2. CLI模式 - 命令行交互

使用方法：
    python main.py              # 启动Web服务
    python main.py --cli        # 启动命令行版本
    python main.py --web        # 启动Web服务（显式）
"""

import os
import sys

# 加载环境变量（从.env文件）
try:
    from dotenv import load_dotenv
    load_dotenv()  # 加载.env文件中的环境变量
except ImportError:
    pass  # 如果没有安装python-dotenv，直接使用系统环境变量

import config
from logger import get_logger


def run_web():
    """启动Web服务"""
    from web_app import run_server
    run_server(host="0.0.0.0", port=8000)


def run_cli():
    """启动命令行交互程序"""
    # 导入CLI相关模块
    from agent.base_agent import (
        ConversationalAgent,
        ReActAgent,
        OpenAIFunctionsAgent,
    )
    from tools.search_tool import search_tool
    from tools.calculator_tool import calculator_tool
    from tools.weather_tool import weather_tool
    from tools.datetime_tool import datetime_tool
    from tools.file_tool import file_tool

    # 支持的模型提供商列表
    PROVIDERS = {
        "1": ("openai", "OpenAI (GPT-3.5/GPT-4)"),
        "2": ("azure", "Azure OpenAI"),
        "3": ("deepseek", "DeepSeek"),
        "4": ("zhipu", "智谱AI (GLM)"),
        "5": ("moonshot", "Moonshot (Kimi)"),
        "6": ("ollama", "Ollama (本地模型)"),
        "7": ("custom", "自定义API"),
    }

    def select_provider() -> str:
        print("\n支持的模型提供商：")
        for key, (provider, desc) in PROVIDERS.items():
            print(f"  {key}. {desc}")
        
        current_provider = config.LLM_PROVIDER
        print(f"\n当前配置: {current_provider}")
        
        try:
            choice = input("\n请选择提供商 (1-7，回车使用当前配置): ").strip()
            if choice in PROVIDERS:
                return PROVIDERS[choice][0]
            return current_provider
        except EOFError:
            return current_provider

    def select_model(provider: str) -> str:
        llm_config = config.get_llm_config(provider)
        default_model = llm_config.get("model_name", "")
        
        suggested_models = {
            "openai": ["gpt-4", "gpt-4-turbo", "gpt-3.5-turbo"],
            "azure": ["使用Azure部署名称"],
            "deepseek": ["deepseek-chat", "deepseek-coder"],
            "zhipu": ["glm-4", "glm-3-turbo"],
            "moonshot": ["moonshot-v1-8k", "moonshot-v1-32k"],
            "ollama": ["llama2", "llama3", "mistral", "qwen"],
            "custom": ["输入自定义模型名称"],
        }
        
        print(f"\n{provider} 常用模型：")
        for model in suggested_models.get(provider, []):
            print(f"  - {model}")
        
        print(f"\n当前默认模型: {default_model}")
        
        try:
            model_input = input("请输入模型名称（回车使用默认）: ").strip()
            return model_input if model_input else default_model
        except EOFError:
            return default_model

    def create_agent(agent_type: str = "conversational", provider: str = None, model_name: str = None):
        log = get_logger("cli")
        log.info(f"创建 {agent_type} Agent (provider={provider}, model={model_name})")

        print(f"\n正在创建 {agent_type} Agent...")
        
        if agent_type == "react":
            agent = ReActAgent(provider=provider, model_name=model_name)
        elif agent_type == "functions":
            agent = OpenAIFunctionsAgent(provider=provider, model_name=model_name)
        else:
            agent = ConversationalAgent(provider=provider, model_name=model_name)
        
        tools = [
            calculator_tool, search_tool, weather_tool, datetime_tool, file_tool,
        ]
        agent.register_tools(tools)
        
        try:
            agent.build()
            print(f"\n{agent_type} Agent 创建成功！\n")
            return agent
        except Exception as e:
            print(f"\n创建Agent失败: {str(e)}")
            print("请检查API密钥配置是否正确。\n")
            sys.exit(1)

    def run_demos(agent: ConversationalAgent):
        print("\n" + "="*60)
        print("开始演示各种工具的使用")
        print("="*60)
        
        demo_queries = [
            "请帮我计算：125的平方根乘以17等于多少？",
            "现在是什么时间？今天是哪一年哪月哪日？",
            "请搜索：什么是大型语言模型(LLM)？",
            "北京今天的天气怎么样？",
            "请列出当前目录下的所有文件和文件夹",
            "请计算圆周率的前20位，然后告诉我现在的日期",
        ]
        
        for i, query in enumerate(demo_queries, 1):
            print(f"\n{'─'*60}")
            print(f"演示 {i}/{len(demo_queries)}")
            print(f"{'─'*60}")
            print(f"\n用户: {query}\n")
            
            result = agent.run(query)
            print(f"\nAgent: {result}")
            
            if i < len(demo_queries):
                input("\n按Enter键继续下一个演示...")

    def interactive_mode(agent: ConversationalAgent):
        print("\n" + "="*60)
        print("进入交互式对话模式")
        print("输入 'quit' 或 'exit' 退出程序")
        print("输入 'clear' 清空对话历史")
        print("="*60 + "\n")
        
        while True:
            try:
                user_input = input("你: ").strip()
                
                if user_input.lower() in ['quit', 'exit', 'q']:
                    print("\n感谢使用！再见！\n")
                    break
                
                if user_input.lower() == 'clear':
                    agent.reset_memory()
                    print("对话历史已清空\n")
                    continue
                
                if not user_input:
                    continue
                
                print()
                result = agent.run(user_input)
                print(f"\nAgent: {result}\n")
                
            except KeyboardInterrupt:
                print("\n\n程序被中断，感谢使用！再见！\n")
                break
            except Exception as e:
                print(f"\n发生错误：{str(e)}\n")

    # CLI主函数逻辑
    print("\n" + "="*60)
    print("  LangChain Agent 演示程序")
    print("  功能：多工具智能助手（支持多种模型提供商）")
    print("="*60)
    
    # 选择模型提供商
    provider = select_provider()
    
    # 选择模型
    model_name = select_model(provider)
    
    # 选择Agent类型
    print("\n支持的Agent类型：")
    print("  1. conversational - 对话型（默认）")
    print("  2. react - ReAct推理型")
    print("  3. functions - OpenAI Functions型")
    
    try:
        choice = input("\n请选择Agent类型 (1-3，默认1): ").strip()
        if choice == "2":
            agent_type = "react"
        elif choice == "3":
            agent_type = "functions"
        else:
            agent_type = "conversational"
    except EOFError:
        agent_type = "conversational"
    
    # 创建Agent
    agent = create_agent(agent_type, provider, model_name)
    
    # 选择运行模式
    print("\n请选择运行模式：")
    print("  1. 运行演示（展示各种工具功能）")
    print("  2. 交互模式（自由对话）")
    
    try:
        mode = input("\n请选择 (1-2): ").strip()
    except EOFError:
        mode = "1"
    
    if mode == "2":
        interactive_mode(agent)
    else:
        run_demos(agent)
        
        try:
            again = input("\n是否进入交互模式继续对话？(y/n): ").strip().lower()
            if again == 'y':
                interactive_mode(agent)
        except EOFError:
            pass


def main():
    """主入口函数"""
    # 检查命令行参数
    if len(sys.argv) > 1:
        if sys.argv[1] == '--cli':
            print("启动命令行模式...")
            run_cli()
            return
        elif sys.argv[1] == '--web':
            print("启动Web服务模式...")
            run_web()
            return
        elif sys.argv[1] in ['--help', '-h']:
            print(__doc__)
            return
        else:
            print(f"未知参数: {sys.argv[1]}")
            print("使用 --help 查看帮助")
            sys.exit(1)
    
    # 默认启动Web服务
    run_web()


if __name__ == "__main__":
    main()
