"""
Prompt 模板管理器

功能：
- 从 YAML 文件加载 prompt 模板
- 支持多角色（assistant / coder / analyst / customer_service）
- 变量插值（{agent_name}, {max_iterations}, {tools_list} 等）
- 模板列表与热加载
- 回退到 config.py 默认值（YAML 不可用时）

用法:
    from prompt_manager import PromptManager
    pm = PromptManager()
    prompt = pm.render("coder", agent_name="CodeBot", tools_list="...")
    # 或直接使用快捷函数:
    from prompt_manager import get_prompt
    prompt = get_prompt("assistant")
"""

import os
from pathlib import Path
from typing import Dict, List, Optional

import config
from logger import get_logger

log = get_logger(__name__)

# ==================== 模板目录 ====================

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


# ==================== Prompt 管理器 ====================

class PromptManager:
    """
    Prompt 模板管理器

    从 prompts/ 目录加载 YAML 模板，支持变量渲染。
    """

    # 默认变量值
    DEFAULT_VARIABLES = {
        "agent_name": "智能助手",
        "max_iterations": str(config.MAX_ITERATIONS),
        "tools_list": "- 网络搜索：搜索互联网上的实时信息\n"
                      "- 数学计算：精确计算数学表达式\n"
                      "- 天气查询：查询城市天气\n"
                      "- 日期时间：获取当前日期和时间\n"
                      "- 文件操作：读写和管理文件",
    }

    def __init__(self, prompts_dir: Path = None):
        self.prompts_dir = prompts_dir or PROMPTS_DIR
        self._cache: Dict[str, dict] = {}
        self._load_all()

    def _load_all(self):
        """加载所有 YAML 模板到缓存"""
        if not self.prompts_dir.exists():
            log.warning(f"Prompt 模板目录不存在: {self.prompts_dir}，使用默认 prompt")
            return

        try:
            import yaml
        except ImportError:
            log.warning("PyYAML 未安装，使用默认 prompt。安装: pip install pyyaml")
            return

        for f in sorted(self.prompts_dir.glob("*.yaml")):
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    template = yaml.safe_load(fh)
                if template and "name" in template:
                    self._cache[template["name"]] = template
                    log.debug(f"加载模板: {template['name']} (v{template.get('version', '?')})")
            except Exception as e:
                log.warning(f"加载模板失败 {f.name}: {e}")

        if self._cache:
            log.info(f"已加载 {len(self._cache)} 个 prompt 模板: {list(self._cache.keys())}")

    def list_templates(self) -> List[Dict[str, str]]:
        """
        列出所有可用模板

        Returns:
            [{"name": "assistant", "description": "...", "version": "1.0"}, ...]
        """
        if not self._cache:
            return [{"name": "default", "description": "内置默认 prompt", "version": "-"}]

        return [
            {
                "name": t["name"],
                "description": t.get("description", ""),
                "version": t.get("version", "?"),
            }
            for t in self._cache.values()
        ]

    def get_template(self, name: str) -> Optional[dict]:
        """获取指定名称的原始模板"""
        return self._cache.get(name)

    def render(self, name: str, **kwargs) -> str:
        """
        渲染指定模板

        Args:
            name: 模板名称 (assistant / coder / analyst / customer_service)
            **kwargs: 自定义变量值（覆盖默认值）

        Returns:
            str: 渲染后的 system prompt
        """
        # 合并默认变量和用户变量
        variables = {**self.DEFAULT_VARIABLES, **kwargs}

        template = self._cache.get(name)
        if template and "system_prompt" in template:
            raw = template["system_prompt"]
            rendered = raw.format(**variables)
            log.debug(f"渲染模板: {name} (v{template.get('version', '?')})")
            return rendered

        # 回退：自定义名称 -> assistant -> config 默认值
        if name not in self._cache:
            log.warning(f"模板 '{name}' 不存在，回退到 assistant")
            return self.render("assistant", **kwargs)

        log.warning(f"模板 '{name}' 缺少 system_prompt 字段，使用 config 默认值")
        return config.SYSTEM_PROMPT

    def reload(self):
        """热加载：清空缓存并重新读取所有模板"""
        self._cache.clear()
        self._load_all()
        log.info(f"模板已重新加载 ({len(self._cache)} 个)")


# ==================== 全局实例与快捷函数 ====================

_prompt_manager: Optional[PromptManager] = None


def get_prompt_manager() -> PromptManager:
    """获取全局 PromptManager 实例（懒加载）"""
    global _prompt_manager
    if _prompt_manager is None:
        _prompt_manager = PromptManager()
    return _prompt_manager


def get_prompt(name: str = "assistant", **kwargs) -> str:
    """
    快捷函数：获取渲染后的 prompt

    Args:
        name: 模板名称
        **kwargs: 变量覆盖

    Returns:
        str: system prompt
    """
    return get_prompt_manager().render(name, **kwargs)


def list_prompts() -> List[Dict[str, str]]:
    """快捷函数：列出所有可用模板"""
    return get_prompt_manager().list_templates()


def reload_prompts():
    """快捷函数：热加载所有模板"""
    get_prompt_manager().reload()
