"""计算器工具 — 安全的数学表达式求值"""
import ast
import operator
import re
from tools.base import BaseTool, ToolPermission, tool_registry


class CalculatorTool(BaseTool):
    name = "calculator"
    description = "数学计算工具。当需要计算数学题、数字运算时使用。输入为数学表达式如 2+3*4 或 sqrt(16)。"
    permission = ToolPermission.READ
    timeout = 5.0
    cache_ttl = 60
    tags = ["math", "compute"]

    BINARY_OPS = {
        ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
    }
    MATH_FUNCTIONS = {
        "abs": abs, "round": round, "pow": pow,
        "sqrt": lambda x: x ** 0.5,
        "sin": lambda x: __import__("math").sin(x),
        "cos": lambda x: __import__("math").cos(x),
        "tan": lambda x: __import__("math").tan(x),
        "log": lambda x: __import__("math").log(x),
        "exp": lambda x: __import__("math").exp(x),
    }

    def __init__(self, precision: int = 10):
        self.precision = precision

    def _eval(self, node):
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return float(node.value)
            raise ValueError(f"不支持的常量: {type(node.value)}")
        if isinstance(node, ast.BinOp):
            op = self.BINARY_OPS.get(type(node.op))
            if not op:
                raise ValueError(f"不支持的运算符: {node.op}")
            return op(self._eval(node.left), self._eval(node.right))
        if isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.USub):
                return -self._eval(node.operand)
            if isinstance(node.op, ast.UAdd):
                return self._eval(node.operand)
            raise ValueError(f"不支持的一元运算符: {node.op}")
        if isinstance(node, ast.Call):
            name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr
            if name in self.MATH_FUNCTIONS:
                args = [self._eval(a) for a in node.args]
                return self.MATH_FUNCTIONS[name](*args)
            raise ValueError(f"不支持的函数: {name}")
        raise ValueError(f"不支持的表达式: {type(node)}")

    def _run(self, expression: str) -> str:
        expr = expression.strip().replace("^", "**")
        tree = ast.parse(expr, mode="eval")
        result = self._eval(tree.body)
        formatted = f"{result:.{self.precision}f}".rstrip("0").rstrip(".")
        return f"计算结果：{expression} = {formatted}"


calculator_tool_instance = CalculatorTool()
calculator_tool = calculator_tool_instance.to_langchain_tool()
tool_registry.register(calculator_tool_instance)
