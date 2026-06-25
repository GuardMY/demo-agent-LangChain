"""
文件操作工具模块
提供安全的文件读写、文件信息查询等功能

安全措施：
- 路径遍历防护（目录穿越攻击）
- 符号链接解析与验证
- 文件大小限制
- 写入文件类型白名单
- 敏感系统路径黑名单
"""

import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set

import config
from tools.base import BaseTool, ToolPermission, tool_registry


# ==================== 安全配置 ====================

# 最大读取文件大小（10MB）
MAX_READ_SIZE = 10 * 1024 * 1024

# 最大写入文件大小（5MB）
MAX_WRITE_SIZE = 5 * 1024 * 1024

# 允许写入的文件扩展名白名单
ALLOWED_WRITE_EXTENSIONS: Set[str] = {
    # 文本文件
    ".txt", ".md", ".csv", ".json", ".yaml", ".yml", ".xml", ".html", ".css", ".js",
    ".py", ".java", ".cpp", ".c", ".h", ".rs", ".go", ".ts", ".jsx", ".tsx",
    ".sh", ".bat", ".ps1", ".cfg", ".ini", ".toml", ".env",
    # 日志文件
    ".log",
    # 数据文件
    ".sql", ".sqlite", ".db",
}

# 禁止访问的路径关键词（系统敏感路径）
FORBIDDEN_PATH_KEYWORDS = [
    "/etc/", "/boot/", "/sys/", "/proc/", "/dev/",
    "C:\\Windows", "C:\\windows", "C:\\WINDOWS",
    "\\Windows\\", "\\windows\\",
    "System32", "system32",
    ".ssh", ".gnupg", ".aws",
    "/var/run", "/var/log/secure",
    "\\AppData\\Roaming\\",
    "NTUSER.DAT", "SAM", "SYSTEM",
]


class FileOperationTool(BaseTool):
    """
    安全的文件操作工具类

    继承 BaseTool 获得缓存/超时/权限/异步等标准能力。
    """

    name = "file_operations"
    description = """文件操作工具，用于读取、写入文件和列出目录内容。
当用户需要查看文件内容、创建或修改文件、浏览目录结构时使用此工具。
输入应该是 JSON 格式的操作指令。"""
    permission = ToolPermission.SYSTEM
    timeout = 15.0
    cache_ttl = 0  # 文件操作不缓存
    tags = ["file", "system"]

    def __init__(self, root_dir: Path = None):
        """
        初始化文件操作工具

        Args:
            root_dir: 允许操作的根目录，默认为项目根目录
        """
        self.root_dir = (root_dir or config.BASE_DIR).resolve()

    def _get_full_path(self, path: str) -> Path:
        """
        将相对路径转换为绝对路径，并进行安全验证

        安全措施：
        1. 先 resolve() 解析规范路径（消除 .. 和符号链接）
        2. 检查解析后的路径是否在 root_dir 内
        3. 检查是否包含敏感系统路径

        Args:
            path: 相对路径或绝对路径

        Returns:
            Path: 安全的绝对路径对象

        Raises:
            ValueError: 路径不安全或超出允许范围
        """
        user_path = Path(path)

        # 如果输入是绝对路径，先转换为相对于 root_dir 检查
        # 注意：即便是绝对路径，也必须约束在 root_dir 内
        if user_path.is_absolute():
            # 将绝对路径限制在 root_dir 内：
            # 取路径相对于根的部分，拼接回 root_dir
            try:
                # 尝试将绝对路径转为相对路径（如果它在 root_dir 子树内）
                relative = user_path.relative_to(self.root_dir)
                full_path = (self.root_dir / relative).resolve()
            except ValueError:
                # 绝对路径不在 root_dir 子树内，拒绝
                raise ValueError(
                    f"安全限制：不允许访问 root_dir 之外的路径 '{path}'。\n"
                    f"允许的根目录: {self.root_dir}"
                )
        else:
            # 相对路径：直接拼接到 root_dir 后解析
            full_path = (self.root_dir / user_path).resolve()

        # ===== 安全检查 1：路径必须在 root_dir 内 =====
        try:
            full_path.relative_to(self.root_dir)
        except ValueError:
            raise ValueError(
                f"安全限制：路径遍历攻击被阻止。\n"
                f"请求路径: {path}\n"
                f"解析路径: {full_path}\n"
                f"允许目录: {self.root_dir}"
            )

        # ===== 安全检查 2：符号链接目标也必须在 root_dir 内 =====
        if full_path.is_symlink():
            real_target = full_path.resolve()
            try:
                real_target.relative_to(self.root_dir)
            except ValueError:
                raise ValueError(
                    f"安全限制：符号链接指向了允许范围之外的目标。\n"
                    f"链接: {full_path}\n"
                    f"目标: {real_target}"
                )

        # ===== 安全检查 3：检查是否包含敏感路径 =====
        path_str = str(full_path).replace("\\", "/")
        for keyword in FORBIDDEN_PATH_KEYWORDS:
            normalized_keyword = keyword.replace("\\", "/")
            if normalized_keyword.lower() in path_str.lower():
                raise ValueError(
                    f"安全限制：禁止访问系统敏感路径 '{keyword}'。\n"
                    f"请求路径: {path}"
                )

        return full_path

    def read_file(self, file_path: str) -> str:
        """
        安全地读取文件内容

        Args:
            file_path: 文件路径（相对或绝对）

        Returns:
            str: 文件内容，或错误信息
        """
        try:
            full_path = self._get_full_path(file_path)

            if not full_path.exists():
                return f"错误：文件 '{full_path.name}' 不存在"
            if not full_path.is_file():
                return f"错误：'{full_path.name}' 不是文件"

            # 检查文件大小
            file_size = full_path.stat().st_size
            if file_size > MAX_READ_SIZE:
                return (
                    f"错误：文件过大，无法读取。\n"
                    f"文件大小: {file_size / (1024*1024):.1f} MB\n"
                    f"限制: {MAX_READ_SIZE / (1024*1024):.0f} MB"
                )

            # 使用 UTF-8 编码读取文件
            try:
                with open(full_path, 'r', encoding='utf-8') as f:
                    content = f.read(MAX_READ_SIZE + 1)  # +1 用于检测截断
            except UnicodeDecodeError:
                return f"错误：文件 '{full_path.name}' 不是有效的 UTF-8 文本文件，无法读取。"

            truncated = len(content) > MAX_READ_SIZE
            if truncated:
                content = content[:MAX_READ_SIZE]

            result = f"成功读取文件 '{full_path.name}':\n\n{content}"
            if truncated:
                result += "\n\n⚠️ [文件过大，内容已截断]"

            return result

        except ValueError as e:
            return f"安全错误：{str(e)}"
        except PermissionError:
            return f"错误：没有权限读取文件 '{file_path}'"
        except Exception as e:
            return f"读取文件时发生错误：{str(e)}"

    def write_file(self, file_path: str, content: str) -> str:
        """
        安全地写入内容到文件（会覆盖已有文件）

        安全措施：
        - 检查文件扩展名是否在白名单中
        - 检查内容大小是否超过限制
        - 路径安全验证

        Args:
            file_path: 文件路径
            content: 要写入的内容

        Returns:
            str: 操作结果信息
        """
        try:
            full_path = self._get_full_path(file_path)

            # 检查扩展名白名单
            suffix = full_path.suffix.lower()
            if not suffix:
                return (
                    f"安全限制：文件缺少扩展名，写入被拒绝。\n"
                    f"允许的扩展名: {', '.join(sorted(ALLOWED_WRITE_EXTENSIONS))}"
                )
            if suffix not in ALLOWED_WRITE_EXTENSIONS:
                return (
                    f"安全限制：不允许写入 '{suffix}' 类型的文件。\n"
                    f"允许的扩展名: {', '.join(sorted(ALLOWED_WRITE_EXTENSIONS))}"
                )

            # 检查内容大小
            content_bytes = content.encode('utf-8')
            if len(content_bytes) > MAX_WRITE_SIZE:
                return (
                    f"错误：内容过大，无法写入。\n"
                    f"内容大小: {len(content_bytes) / (1024*1024):.1f} MB\n"
                    f"限制: {MAX_WRITE_SIZE / (1024*1024):.0f} MB"
                )

            # 确保父目录存在
            full_path.parent.mkdir(parents=True, exist_ok=True)

            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(content)

            return f"成功写入文件 '{full_path.name}' ({len(content_bytes)} bytes)"

        except ValueError as e:
            return f"安全错误：{str(e)}"
        except PermissionError:
            return f"错误：没有权限写入文件 '{file_path}'"
        except Exception as e:
            return f"写入文件时发生错误：{str(e)}"

    def list_directory(self, dir_path: str = ".") -> str:
        """
        列出目录中的文件和子目录

        Args:
            dir_path: 目录路径，默认为当前目录

        Returns:
            str: 目录内容列表
        """
        try:
            full_path = self._get_full_path(dir_path)

            if not full_path.exists():
                return f"错误：目录 '{dir_path}' 不存在"
            if not full_path.is_dir():
                return f"错误：'{dir_path}' 不是目录"

            # 列出目录内容（最多 200 条）
            items = []
            max_items = 200
            for item in sorted(full_path.iterdir()):
                if len(items) >= max_items:
                    items.append(f"... 还有更多文件 ({max_items}/{sum(1 for _ in full_path.iterdir())})")
                    break

                try:
                    size = item.stat().st_size if item.is_file() else 0
                    mtime = datetime.fromtimestamp(item.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                    item_type = "[文件]" if item.is_file() else "[目录]"
                    size_str = f"{size} bytes" if size < 1024 else f"{size / 1024:.1f} KB"
                    items.append(f"{item_type} {item.name} | 大小: {size_str} | 修改: {mtime}")
                except (PermissionError, OSError):
                    items.append(f"[无权限] {item.name}")

            if not items:
                return f"目录 '{full_path.name}' 为空"

            return f"目录 '{full_path.name}' 内容:\n\n" + "\n".join(items)

        except ValueError as e:
            return f"安全错误：{str(e)}"
        except PermissionError:
            return f"错误：没有权限访问目录 '{dir_path}'"
        except Exception as e:
            return f"列出目录时发生错误：{str(e)}"

    def get_file_info(self, file_path: str) -> str:
        """
        获取文件的详细信息

        Args:
            file_path: 文件路径

        Returns:
            str: 文件详细信息
        """
        try:
            full_path = self._get_full_path(file_path)

            if not full_path.exists():
                return f"错误：文件 '{full_path.name}' 不存在"

            stat = full_path.stat()
            size = stat.st_size
            info = {
                "名称": full_path.name,
                "路径": str(full_path),
                "类型": "文件" if full_path.is_file() else ("目录" if full_path.is_dir() else "其他"),
                "大小": f"{size} bytes ({size / 1024:.2f} KB, {size / (1024*1024):.2f} MB)",
                "后缀名": full_path.suffix or "(无)",
                "修改时间": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "创建时间": datetime.fromtimestamp(stat.st_ctime).strftime("%Y-%m-%d %H:%M:%S"),
            }

            # 如果是文件，检查是否为符号链接
            if full_path.is_symlink():
                info["符号链接目标"] = str(full_path.resolve())

            return "文件信息:\n" + "\n".join([f"  {k}: {v}" for k, v in info.items()])

        except ValueError as e:
            return f"安全错误：{str(e)}"
        except PermissionError:
            return f"错误：没有权限获取文件信息 '{file_path}'"
        except Exception as e:
            return f"获取文件信息时发生错误：{str(e)}"

    def _run(self, input_str: str) -> str:
        """
        BaseTool 要求的统一入口。解析输入并分发到具体操作。
        支持 JSON 或自然语言格式。
        """
        import json
        # 尝试 JSON
        try:
            params = json.loads(input_str)
            if isinstance(params, dict):
                return self._dispatch(params.get("operation", ""), params.get("path", ""), params.get("content", ""))
        except (json.JSONDecodeError, TypeError):
            pass
        # 自然语言回退
        lower = input_str.strip().lower()
        if lower.startswith("read "):
            return self.read_file(input_str[5:].strip())
        if lower.startswith("list "):
            return self.list_directory(input_str[5:].strip())
        if lower.startswith("info "):
            return self.get_file_info(input_str[5:].strip())
        if lower.startswith("write "):
            parts = input_str[6:].strip().split(" ", 1)
            if len(parts) >= 2:
                return self.write_file(parts[0], parts[1])
            return "错误：写入格式为 'write <路径> <内容>'"
        return f"无法解析指令。支持: read/write/list/info 或 JSON"

    def _dispatch(self, operation: str = "", path: str = "", content: str = "") -> str:
        """
        根据操作类型分发

        Args:
            operation: 操作类型 ('read', 'write', 'list', 'info')
            path: 文件或目录路径
            content: 写入内容（仅写操作需要）

        Returns:
            str: 操作结果
        """
        if operation == "read":
            return self.read_file(path)
        elif operation == "write":
            if not content:
                return "错误：写入操作需要提供 content 参数"
            return self.write_file(path, content)
        elif operation == "list":
            return self.list_directory(path or ".")
        elif operation == "info":
            return self.get_file_info(path)
        else:
            return (
                f"未知操作：'{operation}'。"
                f"支持的操作: read, write, list, info\n"
                f"示例: read path='README.md'\n"
                f"      write path='output.txt' content='Hello'\n"
                f"      list path='./src'\n"
                f"      info path='config.py'"
            )


# ==================== LangChain Tool 适配包装器 ====================

class FileToolLangChainWrapper:
    """
    将 FileOperationTool 适配为 LangChain Tool 的 func 接口

    LangChain Tool 的 func 接收单个字符串参数，
    此包装器将字符串解析为 operation + path + content。
    """

    def __init__(self, file_ops: FileOperationTool):
        self.file_ops = file_ops

    def __call__(self, input_str: str) -> str:
        """
        解析输入并执行文件操作

        支持两种输入格式：
        1. JSON: {"operation": "read", "path": "file.txt", "content": "..."}
        2. 自然语言关键词: "read file.txt" / "list ./dir" / "write file.txt content"

        Args:
            input_str: 操作指令

        Returns:
            str: 操作结果
        """
        import json

        # 尝试 JSON 格式
        try:
            params = json.loads(input_str)
            if isinstance(params, dict):
                op = params.get("operation", "")
                p = params.get("path", "")
                c = params.get("content", "")
                return self.file_ops.run(operation=op, path=p, content=c)
        except (json.JSONDecodeError, TypeError):
            pass

        # 回退到自然语言解析
        input_lower = input_str.strip().lower()

        if input_lower.startswith("read "):
            path = input_str[5:].strip()
            return self.file_ops.read_file(path)
        elif input_lower.startswith("list "):
            path = input_str[5:].strip()
            return self.file_ops.list_directory(path)
        elif input_lower.startswith("info "):
            path = input_str[5:].strip()
            return self.file_ops.get_file_info(path)
        elif input_lower.startswith("write "):
            # 格式: write path content
            parts = input_str[6:].strip().split(" ", 1)
            if len(parts) >= 2:
                return self.file_ops.write_file(parts[0], parts[1])
            else:
                return "错误：写入格式为 'write <路径> <内容>'"
        else:
            return (
                f"无法解析指令 '{input_str}'。\n"
                f"支持的格式:\n"
                f"  - read <文件路径>\n"
                f"  - write <文件路径> <内容>\n"
                f"  - list <目录路径>\n"
                f"  - info <文件路径>\n"
                f"  - JSON: {{\"operation\": \"read\", \"path\": \"...\"}}"
            )


# 创建全局工具实例并注册
_file_ops = FileOperationTool()
file_tool = _file_ops.to_langchain_tool()
tool_registry.register(_file_ops)
