"""
多模态输入支持模块

功能：
- Base64 图片输入解析
- 图片描述请求（需要 Vision 模型）
- 文件上传预处理
- 安全校验（文件类型、大小）

支持的 Vision 模型:
- OpenAI: gpt-4o, gpt-4-vision-preview
- Anthropic: claude-sonnet-4-6, claude-opus-4-8

用法:
    from multimodal import MultimodalHandler
    handler = MultimodalHandler()
    result = handler.process_image(base64_data, query="描述这张图片")
"""

import base64
import io
import os
from typing import List, Optional, Tuple

from logger import get_logger

log = get_logger(__name__)

# 配置
MAX_IMAGE_SIZE = 20 * 1024 * 1024  # 20MB
ALLOWED_MIME_TYPES = {
    "image/png", "image/jpeg", "image/jpg", "image/gif", "image/webp",
    "image/bmp", "image/tiff",
}


class MultimodalHandler:
    """多模态处理器"""

    @staticmethod
    def validate_image(data: bytes, mime_type: str = None) -> Tuple[bool, str]:
        """
        验证图片安全性

        Returns:
            (valid, error_message)
        """
        if len(data) > MAX_IMAGE_SIZE:
            return False, f"图片过大: {len(data) / (1024*1024):.1f}MB (最大 {MAX_IMAGE_SIZE / (1024*1024):.0f}MB)"

        if mime_type and mime_type not in ALLOWED_MIME_TYPES:
            return False, f"不支持的图片格式: {mime_type}"

        # 检测魔数（Magic Bytes）
        magic = data[:8]
        png_magic = b'\x89PNG\r\n\x1a\n'
        jpeg_magic = b'\xff\xd8\xff'
        gif_magic = (b'GIF87a', b'GIF89a')
        webp_magic = b'RIFF'

        is_valid = (
            magic[:len(png_magic)] == png_magic
            or magic[:len(jpeg_magic)] == jpeg_magic
            or magic[:6] in gif_magic
            or (magic[:4] == webp_magic and magic[8:12] == b'WEBP')
        )
        if not is_valid:
            return False, "文件不是有效图片（魔数检测失败）"

        return True, ""

    @staticmethod
    def encode_file(file_path: str) -> Tuple[str, str]:
        """
        读取文件并编码为 Base64

        Returns:
            (base64_string, mime_type)
        """
        import mimetypes
        mime_type, _ = mimetypes.guess_type(file_path)
        mime_type = mime_type or "image/png"

        with open(file_path, "rb") as f:
            data = f.read()

        valid, error = MultimodalHandler.validate_image(data, mime_type)
        if not valid:
            raise ValueError(error)

        encoded = base64.b64encode(data).decode("utf-8")
        return encoded, mime_type

    @staticmethod
    def build_openai_message(base64_data: str, mime_type: str, query: str) -> dict:
        """
        构建 OpenAI Vision 格式的消息

        Args:
            base64_data: Base64 编码的图片数据
            mime_type: MIME 类型
            query: 用户的问题

        Returns:
            OpenAI 兼容的消息 dict
        """
        return {
            "role": "user",
            "content": [
                {"type": "text", "text": query or "请描述这张图片"},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime_type};base64,{base64_data}",
                        "detail": "auto",
                    },
                },
            ],
        }

    @staticmethod
    def build_claude_message(base64_data: str, mime_type: str, query: str) -> dict:
        """构建 Anthropic Claude Vision 格式的消息"""
        return {
            "role": "user",
            "content": [
                {"type": "text", "text": query or "请描述这张图片"},
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": mime_type,
                        "data": base64_data,
                    },
                },
            ],
        }


# 全局实例
multimodal_handler = MultimodalHandler()
