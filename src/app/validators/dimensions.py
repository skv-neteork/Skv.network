import re, math
from typing import Dict, Tuple, Any
from .physical_quantity import PhysicalQuantity, DimensionalityError

class LaTeXDimensionValidator:
    def __init__(self, symbol_table: Dict[str, PhysicalQuantity]):
        self.symbols = symbol_table
        self._safe_math = {
            'sin': math.sin, 'cos': math.cos, 'tan': math.tan,
            'sqrt': lambda x: x**0.5 if isinstance(x, (int,float)) else x**0.5,
            'exp': lambda x: x.exp() if isinstance(x, PhysicalQuantity) else math.exp(x),
            'pi': math.pi, 'e': math.e
        }

    def _clean_latex(self, expr: str) -> str:
        e = expr.strip()
        e = re.sub(r'\\frac\{([^{}]+)\}\{([^{}]+)\}', r'(\1)/(\2)', e)
        e = re.sub(r'([^{}\s]+)\^{([^{}]+)}', r'\1**\2', e)
        e = re.sub(r'\\sqrt\{([^{}]+)\}', r'sqrt(\1)', e)
        e = e.replace('\\cdot', '*').replace('\\times', '*')
        e = re.sub(r'([a-zA-Z0-9])\s+([a-zA-Z0-9])', r'\1*\2', e)
        return e

    def validate(self, latex_expr: str) -> Tuple[bool, Any, str]:
        try:
            py_expr = self._clean_latex(latex_expr)
            namespace = {**self.symbols, **self._safe_math, '__builtins__': {}}
            result = eval(py_expr, namespace)
            if not isinstance(result, PhysicalQuantity):
                return False, None, "Result is not a PhysicalQuantity"
            return True, result, "Dimensionally consistent"
        except DimensionalityError as e:
            return False, None, f"DIMENSION ERROR: {str(e)}"
        except Exception as e:
            return False, None, f"PARSE ERROR: {str(e)[:100]}"
