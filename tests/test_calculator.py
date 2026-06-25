"""
计算器工具单元测试
"""

import pytest
from tools.calculator_tool import CalculatorTool


@pytest.fixture
def calc():
    return CalculatorTool(precision=10)


class TestCalculatorBasic:
    """基础运算"""

    @pytest.mark.parametrize("expr,expected", [
        ("1+1", "2"),
        ("2*3", "6"),
        ("10/2", "5"),
        ("2**3", "8"),
        ("10-7", "3"),
        ("10%3", "1"),
        ("-5", "-5"),
        ("+5", "5"),
        ("(2+3)*4", "20"),
        ("2+3*4", "14"),
    ])
    def test_basic_ops(self, calc, expr, expected):
        result = calc.run(expr)
        assert expected in result, f"{expr} should = {expected}, got: {result}"

    def test_decimal_precision(self, calc):
        result = calc.run("10/3")
        assert "3.3333333333" in result or "3.333" in result

    def test_negative_numbers(self, calc):
        result = calc.run("-5 * -3")
        assert "15" in result

    def test_complex_expression(self, calc):
        result = calc.run("(15+25)*(10-5)/2")
        assert "100" in result


class TestCalculatorFunctions:
    """数学函数"""

    def test_sqrt(self, calc):
        result = calc.run("sqrt(16)")
        assert "4" in result

    def test_sqrt_decimal(self, calc):
        result = calc.run("sqrt(2)")
        assert "1.414" in result

    def test_abs(self, calc):
        result = calc.run("abs(-42)")
        assert "42" in result

    def test_round(self, calc):
        result = calc.run("round(3.14159)")
        assert "3" in result

    def test_pow(self, calc):
        """pow 需要通过 ** 运算符: 2**10"""
        result = calc.run("2**10")
        assert "1024" in result

    def test_sin(self, calc):
        result = calc.run("sin(0)")
        assert "0" in result

    def test_cos(self, calc):
        result = calc.run("cos(0)")
        assert "1" in result

    def test_log(self, calc):
        result = calc.run("log(1)")
        assert "0" in result

    def test_exp(self, calc):
        result = calc.run("exp(0)")
        assert "1" in result

    def test_caret_conversion(self, calc):
        """^ 运算符自动转为 **"""
        result = calc.run("2^10")
        assert "1024" in result


class TestCalculatorErrors:
    """错误处理"""

    def test_invalid_syntax(self, calc):
        """无效语法: Python 关键字"""
        result = calc.run("import os")
        assert "不支持" in result or "错误" in result or "error" in result.lower()

    def test_unsupported_function(self, calc):
        result = calc.run("eval('1+1')")
        assert "不支持" in result or "错误" in result

    def test_empty_expression(self, calc):
        result = calc.run("")
        assert "错误" in result or "error" in result.lower()
