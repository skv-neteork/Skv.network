from fastapi import APIRouter, HTTPException
import httpx, json
router = APIRouter()
SANDBOX_URL = "http://172.19.0.8:8000"

# Inlined PhysicalQuantity — no external imports needed
PQ_CODE = """
import math

class DimensionalityError(TypeError):
    pass

class PhysicalQuantity:
    def __init__(self, value: float, m: int = 0, kg: int = 0, s: int = 0):
        self.value = float(value)
        self.dims = (m, kg, s)
    def __repr__(self):
        m, kg, s = self.dims
        parts = []
        if m: parts.append(f"m^{m}" if m != 1 else "m")
        if kg: parts.append(f"kg^{kg}" if kg != 1 else "kg")
        if s: parts.append(f"s^{s}" if s != 1 else "s")
        dim_str = "*".join(parts) if parts else "dimensionless"
        return f"{self.value:.3g} [{dim_str}]"
    def __add__(self, other):
        if not isinstance(other, PhysicalQuantity) or self.dims != other.dims:
            raise DimensionalityError(f"Cannot add {self} and {other}")
        return PhysicalQuantity(self.value + other.value, *self.dims)
    def __sub__(self, other):
        if not isinstance(other, PhysicalQuantity) or self.dims != other.dims:
            raise DimensionalityError(f"Cannot subtract {self} and {other}")
        return PhysicalQuantity(self.value - other.value, *self.dims)
    def __mul__(self, other):
        if isinstance(other, (int, float)):
            return PhysicalQuantity(self.value * other, *self.dims)
        if isinstance(other, PhysicalQuantity):
            new_dims = tuple(a + b for a, b in zip(self.dims, other.dims))
            return PhysicalQuantity(self.value * other.value, *new_dims)
        raise TypeError(f'Cannot multiply by {type(other)}')
    def __rmul__(self, other):
        return self.__mul__(other)
    def __truediv__(self, other):
        if isinstance(other, (int, float)):
            return PhysicalQuantity(self.value / other, *self.dims)
        if isinstance(other, PhysicalQuantity):
            new_dims = tuple(a - b for a, b in zip(self.dims, other.dims))
            return PhysicalQuantity(self.value / other.value, *new_dims)
        raise TypeError(f'Cannot divide by {type(other)}')
    def __pow__(self, power: float):
        new_dims = tuple(int(d * power) if float(d * power) == int(d * power) else d * power for d in self.dims)
        return PhysicalQuantity(self.value ** power, *new_dims)
    def __neg__(self):
        return PhysicalQuantity(-self.value, *self.dims)
    def __repr__(self):
        m, kg, s = self.dims
        parts = []
        if m: parts.append(f'L^{m}' if m != 1 else 'L')
        if kg: parts.append(f'M^{kg}' if kg != 1 else 'M')
        if s: parts.append(f'T^{s}' if s != 1 else 'T')
        dim_str = '*'.join(parts) if parts else 'dimensionless'
        return f'{self.value:.3g} [{dim_str}]'

    def exp(self):
        if self.dims != (0, 0, 0):
            raise DimensionalityError(f"exp() requires dimensionless argument, got {self}")
        return PhysicalQuantity(math.exp(self.value), 0, 0, 0)
    def sqrt(self):
        return self ** 0.5
"""

@router.post("/api/validate/formula")
async def validate_formula(payload: dict):
    """Validate physical formulas for dimensional consistency."""
    formulas = payload.get("formulas", [])
    if not formulas:
        raise HTTPException(400, "No formulas provided")

    # Build sandbox code with inlined validators
    code = PQ_CODE + """
import re, json, math

class LaTeXDimensionValidator:
    def __init__(self, symbols):
        self.symbols = symbols
    def _clean(self, expr):
        e = expr.strip()
        # Handle \\frac{a}{b}
        e = re.sub(r'\\\\frac\\{([^{}]+)\\}\\{([^{}]+)\\}', r'(\\1)/(\\2)', e)
        # Handle x^{y}
        e = re.sub(r'([a-zA-Z0-9_]+)\\^\\{([^{}]+)\\}', r'\\1**(\\2)', e)
        # Handle x^y (simple)
        e = re.sub(r'([a-zA-Z0-9_]+)\\^(\\d+)', r'\\1**\\2', e)
        # Handle \\sqrt{x}
        e = re.sub(r'\\\\sqrt\\{([^{}]+)\\}', r'sqrt(\\1)', e)
        # Replace \\cdot and \\times
        e = e.replace('\\\\cdot', '*').replace('\\\\times', '*')
        # Remove \\left, \\right
        e = e.replace('\\\\left', '').replace('\\\\right', '')
        return e
    def validate(self, expr):
        try:
            py_expr = self._clean(expr)
            namespace = {
                **self.symbols,
                'sqrt': lambda x: x**0.5 if isinstance(x, (int,float)) else x**0.5,
                'exp': lambda x: x.exp() if isinstance(x, PhysicalQuantity) else math.exp(x),
                'pi': math.pi,
                'e': math.e,
                '__builtins__': {}
            }
            result = eval(py_expr, namespace)
            if not isinstance(result, PhysicalQuantity):
                return False, None, "Not a PhysicalQuantity"
            return True, str(result), "OK"
        except DimensionalityError as ex:
            return False, None, str(ex)
        except Exception as ex:
            return False, None, str(ex)[:100]

symbols = {
    "u": PhysicalQuantity(2.0, m=1, kg=0, s=-1),
    "omega": PhysicalQuantity(4.0, m=0, kg=0, s=-1),
    "mu": PhysicalQuantity(0.001, m=-1, kg=1, s=-1),
    "S_ij": PhysicalQuantity(5.0, m=0, kg=0, s=-1),
    "H": PhysicalQuantity(8.0, m=3, kg=0, s=-2),
    "nu": PhysicalQuantity(0.001, m=2, kg=0, s=-1),
    "lambda_t": PhysicalQuantity(0.01, m=0, kg=0, s=2),
    "lambda": PhysicalQuantity(0.04, m=0, kg=0, s=2),
    "dV": PhysicalQuantity(1.0, m=3, kg=0, s=0),
    "lambda_param": PhysicalQuantity(0.04, m=0, kg=0, s=2),
}

validator = LaTeXDimensionValidator(symbols)
formulas = """ + json.dumps(formulas) + """
results = []
for f in formulas:
    ok, res, msg = validator.validate(f)
    results.append({"formula": f, "valid": ok, "dimensions": res, "message": msg})
print(json.dumps(results))
"""

    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(f"{SANDBOX_URL}/run",
            json={"code": code, "language": "python"})
        data = r.json()
        if data.get("status") == "success":
            return json.loads(data["stdout"])
        return {"error": data.get("stderr", "Sandbox failed")[:500]}
