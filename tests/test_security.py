"""
CI 冒烟测试 — 文件工具安全
验证安全加固的核心功能正常工作
"""

import tempfile
import shutil
from pathlib import Path

import pytest


@pytest.fixture
def temp_dir():
    """创建临时测试目录"""
    d = Path(tempfile.mkdtemp())
    yield d
    shutil.rmtree(d)


@pytest.fixture
def file_ops(temp_dir):
    """创建带临时根目录的 FileOperationTool 实例"""
    from tools.file_tool import FileOperationTool
    return FileOperationTool(root_dir=temp_dir)


class TestFileToolSecurity:
    """文件工具安全测试"""

    def test_normal_read(self, file_ops, temp_dir):
        """正常读取文件"""
        (temp_dir / "hello.txt").write_text("hello world", encoding="utf-8")
        result = file_ops.read_file("hello.txt")
        assert "hello world" in result

    def test_path_traversal_blocked(self, file_ops, temp_dir):
        """路径遍历攻击被阻止"""
        outside = Path(tempfile.mkdtemp())
        try:
            (outside / "secret.txt").write_text("secret", encoding="utf-8")
            result = file_ops.read_file(f"../{outside.name}/secret.txt")
            assert "安全" in result or "安全限制" in result or "安全错误" in result
        finally:
            shutil.rmtree(outside)

    def test_absolute_path_blocked(self, file_ops):
        """绝对路径攻击被阻止"""
        result = file_ops.read_file("/etc/passwd")
        assert "安全" in result

    def test_system_path_blocked(self, file_ops):
        """系统敏感路径被阻止"""
        result = file_ops.read_file("C:/Windows/System32/config/SAM")
        assert "安全" in result

    def test_write_allowed_extension(self, file_ops, temp_dir):
        """允许的扩展名写入成功"""
        result = file_ops.write_file("notes.txt", "test content")
        assert "成功" in result

    def test_write_blocked_extension(self, file_ops):
        """被禁止的扩展名写入失败"""
        result = file_ops.write_file("virus.exe", "malicious")
        assert "不允许" in result or "安全" in result

    def test_write_no_extension_blocked(self, file_ops):
        """无扩展名文件被拒绝"""
        result = file_ops.write_file("noextension", "content")
        assert "扩展名" in result or "安全" in result

    def test_list_directory(self, file_ops, temp_dir):
        """列出目录内容"""
        (temp_dir / "a.txt").write_text("a")
        (temp_dir / "subdir").mkdir()
        result = file_ops.list_directory(".")
        assert "a.txt" in result and "subdir" in result

    def test_file_info(self, file_ops, temp_dir):
        """获取文件信息"""
        (temp_dir / "info.txt").write_text("data")
        result = file_ops.get_file_info("info.txt")
        assert "info.txt" in result and "bytes" in result

    def test_run_method_read(self, file_ops, temp_dir):
        """run() 方法读取"""
        (temp_dir / "run_test.txt").write_text("hello")
        result = file_ops.run('{"operation": "read", "path": "run_test.txt"}')
        assert "hello" in result

    def test_run_method_write(self, file_ops):
        """run() 方法写入"""
        result = file_ops.run('{"operation": "write", "path": "output.md", "content": "# Test"}')
        assert "成功" in result
