"""
结构化输出模块

强制 Agent 以预定义的 JSON Schema 格式返回结果，
便于下游系统（API、数据库、前端组件）直接消费。

用法:
    from structured_output import OutputSchema, SchemaType

    # 定义输出格式
    schema = OutputSchema.weather_report()
    # {"city": "...", "temperature": 0, "condition": "...", "humidity": 0}

    # 在 prompt 中注入格式约束
    prompt = schema.to_prompt_instruction()
"""

from typing import Any, Dict, List, Optional


class SchemaType:
    """预定义输出 Schema 类型"""
    WEATHER = "weather"
    CODE = "code"
    ANALYSIS = "analysis"
    SUMMARY = "summary"
    QA = "qa"


class OutputSchema:
    """
    结构化输出 Schema

    定义 Agent 应返回的 JSON 格式，并生成 prompt 指令。
    """

    # 预定义 Schema 注册表
    SCHEMAS: Dict[str, dict] = {
        SchemaType.WEATHER: {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "城市名称"},
                "temperature": {"type": "number", "description": "温度（摄氏度）"},
                "condition": {"type": "string", "description": "天气状况"},
                "humidity": {"type": "number", "description": "湿度百分比"},
                "wind": {"type": "string", "description": "风力描述"},
            },
            "required": ["city", "temperature", "condition"],
        },
        SchemaType.CODE: {
            "type": "object",
            "properties": {
                "language": {"type": "string", "description": "编程语言"},
                "code": {"type": "string", "description": "代码内容"},
                "explanation": {"type": "string", "description": "代码解释"},
                "dependencies": {"type": "array", "items": {"type": "string"}, "description": "依赖列表"},
            },
            "required": ["language", "code"],
        },
        SchemaType.ANALYSIS: {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "分析标题"},
                "summary": {"type": "string", "description": "一句话摘要"},
                "findings": {"type": "array", "items": {"type": "string"}, "description": "关键发现"},
                "data_points": {"type": "array", "items": {"type": "object"}, "description": "数据点"},
                "conclusion": {"type": "string", "description": "结论"},
            },
            "required": ["title", "summary", "conclusion"],
        },
        SchemaType.SUMMARY: {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "主题"},
                "key_points": {"type": "array", "items": {"type": "string"}, "description": "要点"},
                "word_count": {"type": "integer", "description": "字数"},
                "sentiment": {"type": "string", "enum": ["positive", "negative", "neutral"]},
            },
            "required": ["topic", "key_points"],
        },
        SchemaType.QA: {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "用户问题"},
                "answer": {"type": "string", "description": "答案"},
                "confidence": {"type": "number", "description": "置信度 0-1"},
                "sources": {"type": "array", "items": {"type": "string"}, "description": "信息来源"},
            },
            "required": ["answer", "confidence"],
        },
    }

    def __init__(self, schema_type: str = None, custom_schema: dict = None):
        if custom_schema:
            self.schema = custom_schema
        elif schema_type and schema_type in self.SCHEMAS:
            self.schema = self.SCHEMAS[schema_type]
        else:
            self.schema = self.SCHEMAS[SchemaType.QA]

    def to_prompt_instruction(self) -> str:
        """
        生成注入到 system_prompt 的格式指令
        """
        import json
        schema_str = json.dumps(self.schema, ensure_ascii=False, indent=2)
        return (
            "你的回答必须以严格的 JSON 格式返回，不要包含其他文字。\n"
            "JSON Schema 如下：\n"
            f"```json\n{schema_str}\n```\n"
            "确保所有 required 字段都存在，类型正确。"
        )

    @classmethod
    def list_schemas(cls) -> List[dict]:
        return [
            {"type": name, "fields": list(schema.get("properties", {}).keys())}
            for name, schema in cls.SCHEMAS.items()
        ]

    @classmethod
    def get_weather_schema(cls): return cls(SchemaType.WEATHER)
    @classmethod
    def get_code_schema(cls): return cls(SchemaType.CODE)
    @classmethod
    def get_analysis_schema(cls): return cls(SchemaType.ANALYSIS)
    @classmethod
    def get_summary_schema(cls): return cls(SchemaType.SUMMARY)
    @classmethod
    def get_qa_schema(cls): return cls(SchemaType.QA)
