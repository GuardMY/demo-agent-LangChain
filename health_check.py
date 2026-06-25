"""
健康检查模块
提供多层次的系统健康状态检测

检查项：
- LLM API 连通性（各提供商）
- 工具可用性
- 系统资源（内存、运行时间）
- 会话状态
"""

import asyncio
import os
import time
import gc
import sys
from datetime import datetime
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import config


# ==================== 数据模型 ====================

@dataclass
class CheckResult:
    """单项检查结果"""
    name: str
    status: str          # "healthy" | "degraded" | "unhealthy"
    message: str = ""
    latency_ms: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class HealthReport:
    """完整健康报告"""
    status: str          # 综合状态
    timestamp: str
    uptime_seconds: float
    version: str
    checks: List[CheckResult] = field(default_factory=list)

    @property
    def healthy_count(self) -> int:
        return sum(1 for c in self.checks if c.status == "healthy")

    @property
    def degraded_count(self) -> int:
        return sum(1 for c in self.checks if c.status == "degraded")

    @property
    def unhealthy_count(self) -> int:
        return sum(1 for c in self.checks if c.status == "unhealthy")


# ==================== 启动时间追踪 ====================

_start_time = time.time()


def get_uptime_seconds() -> float:
    """获取服务运行时长（秒）"""
    return time.time() - _start_time


def get_memory_usage() -> Dict[str, Any]:
    """获取内存使用信息"""
    try:
        import psutil
        process = psutil.Process(os.getpid())
        mem = process.memory_info()
        return {
            "rss_mb": round(mem.rss / (1024 * 1024), 2),
            "vms_mb": round(mem.vms / (1024 * 1024), 2),
            "cpu_percent": process.cpu_percent(interval=0.1),
        }
    except ImportError:
        # psutil 不可用时的回退
        return {
            "rss_mb": "N/A (pip install psutil)",
            "cpu_percent": "N/A",
        }


def get_python_info() -> Dict[str, str]:
    """获取 Python 环境信息"""
    return {
        "version": sys.version,
        "platform": sys.platform,
    }


# ==================== LLM API 连通性检测 ====================

async def _check_single_llm(provider: str, model_name: str, api_key: str, base_url: str) -> CheckResult:
    """
    检测单个 LLM 提供商的 API 连通性

    发送一个最小的请求（单 token 生成）来验证 API 是否可达。
    """
    start = time.time()

    try:
        # 使用 httpx 发送一个轻量请求
        import httpx

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        # 构造一个最小请求（1 token 生成）
        body = {
            "model": model_name,
            "messages": [{"role": "user", "content": "Hi"}],
            "max_tokens": 1,
            "temperature": 0,
        }

        endpoint = f"{base_url.rstrip('/')}/chat/completions"

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(endpoint, json=body, headers=headers)

        latency = round((time.time() - start) * 1000, 1)

        if resp.status_code == 200:
            return CheckResult(
                name=f"llm:{provider}",
                status="healthy",
                message=f"{provider} API 正常 (HTTP {resp.status_code})",
                latency_ms=latency,
                details={"model": model_name, "base_url": base_url},
            )
        elif resp.status_code == 401 or resp.status_code == 403:
            return CheckResult(
                name=f"llm:{provider}",
                status="degraded",
                message=f"{provider} 认证失败 (HTTP {resp.status_code})",
                latency_ms=latency,
                details={"status_code": resp.status_code, "model": model_name},
            )
        else:
            return CheckResult(
                name=f"llm:{provider}",
                status="unhealthy",
                message=f"{provider} API 异常 (HTTP {resp.status_code})",
                latency_ms=latency,
                details={"status_code": resp.status_code, "body": resp.text[:200]},
            )

    except Exception as e:
        latency = round((time.time() - start) * 1000, 1)
        return CheckResult(
            name=f"llm:{provider}",
            status="unhealthy",
            message=f"{provider} 连接失败: {str(e)[:100]}",
            latency_ms=latency,
        )


async def check_llm_providers() -> List[CheckResult]:
    """
    检测当前配置和常用提供商的 API 连通性

    优先检测当前配置的提供商，可选检测其他提供商。
    """
    results = []

    current_provider = config.LLM_PROVIDER
    llm_config = config.get_llm_config(current_provider)

    # 检测当前提供商
    api_key = llm_config.get("api_key", "")
    base_url = llm_config.get("base_url", "")
    model_name = llm_config.get("model_name", "")

    # OpenAI 的特殊处理
    if current_provider == "openai":
        base_url = base_url or "https://api.openai.com"

    # 只检查有足够配置的提供商
    if api_key and base_url and model_name:
        result = await _check_single_llm(current_provider, model_name, api_key, base_url)
        results.append(result)
    elif current_provider == "ollama":
        # Ollama 本地检测（HTTP GET /api/tags）
        try:
            import httpx
            ollama_url = llm_config.get("base_url", "http://localhost:11434")
            start = time.time()
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{ollama_url.rstrip('/')}/api/tags")
            latency = round((time.time() - start) * 1000, 1)
            if resp.status_code == 200:
                results.append(CheckResult(
                    name="llm:ollama",
                    status="healthy",
                    message=f"Ollama 服务正常运行",
                    latency_ms=latency,
                    details={"url": ollama_url},
                ))
            else:
                results.append(CheckResult(
                    name="llm:ollama",
                    status="unhealthy",
                    message=f"Ollama 响应异常 (HTTP {resp.status_code})",
                    latency_ms=latency,
                ))
        except Exception as e:
            results.append(CheckResult(
                name="llm:ollama",
                status="degraded",
                message=f"Ollama 不可达（可在本地开发环境中忽略）: {str(e)[:80]}",
            ))
    else:
        results.append(CheckResult(
            name=f"llm:{current_provider}",
            status="degraded",
            message=f"无法检测 {current_provider}：缺少 API Key 或 Base URL 配置",
        ))

    return results


# ==================== 工具可用性检查 ====================

async def check_tools() -> List[CheckResult]:
    """检查各工具的可用性"""
    results = []

    # ---- 搜索工具 ----
    try:
        from tools.search_tool import search_tool
        # 检查 DuckDuckGo 库是否可用
        try:
            from duckduckgo_search import DDGS
            results.append(CheckResult(
                name="tool:web_search",
                status="healthy",
                message="DuckDuckGo 搜索可用 (duckduckgo_search)",
                details={"backend": "duckduckgo_search"},
            ))
        except ImportError:
            results.append(CheckResult(
                name="tool:web_search",
                status="degraded",
                message="DuckDuckGo 搜索库未安装，搜索功能不可用",
                details={"fix": "pip install duckduckgo-search"},
            ))
    except Exception as e:
        results.append(CheckResult(
            name="tool:web_search", status="unhealthy", message=str(e)[:100],
        ))

    # ---- 计算器 ----
    try:
        from tools.calculator_tool import calculator_tool_instance
        # 执行一个快速计算
        test_result = calculator_tool_instance.run("1+1")
        ok = "2" in test_result or "2.0" in test_result
        results.append(CheckResult(
            name="tool:calculator",
            status="healthy" if ok else "degraded",
            message="计算器正常" if ok else f"计算器异常: {test_result[:50]}",
        ))
    except Exception as e:
        results.append(CheckResult(
            name="tool:calculator", status="unhealthy", message=str(e)[:100],
        ))

    # ---- 文件工具 ----
    try:
        from tools.file_tool import FileOperationTool
        ops = FileOperationTool()
        test_result = ops.list_directory(".")
        ok = "内容" in test_result or "为空" in test_result or "不存在" in test_result
        results.append(CheckResult(
            name="tool:file_operations",
            status="healthy" if ok else "degraded",
            message="文件工具正常" if ok else f"文件工具异常: {test_result[:50]}",
        ))
    except Exception as e:
        results.append(CheckResult(
            name="tool:file_operations", status="unhealthy", message=str(e)[:100],
        ))

    # ---- 天气工具 ----
    try:
        from tools.weather_tool import weather_tool_instance
        result = weather_tool_instance.run("北京")
        ok = "天气" in result
        results.append(CheckResult(
            name="tool:weather",
            status="healthy" if ok else "degraded",
            message="天气工具正常（模拟数据）" if ok else f"天气工具异常: {result[:50]}",
            details={"mode": "mock", "cities": 12},
        ))
    except Exception as e:
        results.append(CheckResult(
            name="tool:weather", status="unhealthy", message=str(e)[:100],
        ))

    # ---- 日期时间 ----
    try:
        from tools.datetime_tool import datetime_tool_instance
        result = datetime_tool_instance.run()
        ok = "当前时间" in result or "时间" in result
        results.append(CheckResult(
            name="tool:datetime",
            status="healthy" if ok else "degraded",
            message="日期工具正常" if ok else f"日期工具异常: {result[:50]}",
        ))
    except Exception as e:
        results.append(CheckResult(
            name="tool:datetime", status="unhealthy", message=str(e)[:100],
        ))

    return results


# ==================== 系统检查 ====================

async def check_system() -> List[CheckResult]:
    """系统级检查"""
    results = []

    # 内存使用
    mem = get_memory_usage()
    rss = mem.get("rss_mb", 0)
    if isinstance(rss, (int, float)) and rss > 1024:  # > 1GB
        results.append(CheckResult(
            name="system:memory",
            status="degraded",
            message=f"内存使用较高: {rss} MB",
            details=mem,
        ))
    else:
        results.append(CheckResult(
            name="system:memory",
            status="healthy",
            message=f"内存使用正常: {rss} MB",
            details=mem,
        ))

    # Python 环境
    py_info = get_python_info()
    results.append(CheckResult(
        name="system:python",
        status="healthy",
        message=f"Python {py_info['version'].split()[0]}",
        details=py_info,
    ))

    # 会话数量
    from session_manager import session_manager as sm
    active = sm.active_session_count
    if active > 100:
        results.append(CheckResult(
            name="system:sessions",
            status="degraded",
            message=f"活跃会话数较多: {active}",
            details={"active": active},
        ))
    else:
        results.append(CheckResult(
            name="system:sessions",
            status="healthy",
            message=f"活跃会话: {active} 个",
            details={"active": active},
        ))

    return results


# ==================== 综合健康检查 ====================

async def run_health_checks(detailed: bool = False) -> HealthReport:
    """
    运行完整的健康检查

    Args:
        detailed: True 时包含 LLM 连通性检测（可能较慢）

    Returns:
        HealthReport: 健康报告
    """
    checks: List[CheckResult] = []

    # 基础检查（始终运行）
    checks.extend(await check_system())
    checks.extend(await check_tools())

    # 详细检查（按需）
    if detailed:
        checks.extend(await check_llm_providers())

    # 计算综合状态
    unhealthy = [c for c in checks if c.status == "unhealthy"]
    degraded = [c for c in checks if c.status == "degraded"]

    if unhealthy:
        overall = "unhealthy"
    elif degraded:
        overall = "degraded"
    else:
        overall = "healthy"

    return HealthReport(
        status=overall,
        timestamp=datetime.utcnow().isoformat() + "Z",
        uptime_seconds=round(get_uptime_seconds(), 1),
        version="2.1.0",
        checks=checks,
    )


# ==================== 工具函数 ====================

def health_report_to_dict(report: HealthReport) -> Dict[str, Any]:
    """将 HealthReport 转为字典（用于 JSON 响应）"""
    return {
        "status": report.status,
        "timestamp": report.timestamp,
        "uptime_seconds": report.uptime_seconds,
        "uptime_display": f"{int(report.uptime_seconds // 3600)}h "
                         f"{int((report.uptime_seconds % 3600) // 60)}m "
                         f"{int(report.uptime_seconds % 60)}s",
        "version": report.version,
        "summary": {
            "total": len(report.checks),
            "healthy": report.healthy_count,
            "degraded": report.degraded_count,
            "unhealthy": report.unhealthy_count,
        },
        "checks": [
            {
                "name": c.name,
                "status": c.status,
                "message": c.message,
                "latency_ms": c.latency_ms if c.latency_ms else None,
                "details": c.details if c.details else None,
            }
            for c in report.checks
        ],
    }
