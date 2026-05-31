from fastapi import APIRouter, HTTPException, Request
import httpx, json, re, math
router = APIRouter()
SANDBOX_URL = "http://172.19.0.8:8000"

PQ_CODE = """
import math
class DimensionalityError(TypeError):
    pass
class PhysicalQuantity:
    def __init__(self, value, m=0, kg=0, s=0):
        self.value = float(value)
        self.dims = (m, kg, s)
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
        new_dims = tuple(a + b for a, b in zip(self.dims, other.dims))
        return PhysicalQuantity(self.value * other.value, *new_dims)
    def __rmul__(self, other):
        return self.__mul__(other)
    def __truediv__(self, other):
        if isinstance(other, (int, float)):
            return PhysicalQuantity(self.value / other, *self.dims)
        new_dims = tuple(a - b for a, b in zip(self.dims, other.dims))
        return PhysicalQuantity(self.value / other.value, *new_dims)
    def __pow__(self, power):
        new_dims = tuple(int(d * power) if (d * power).is_integer() else d * power for d in self.dims)
        return PhysicalQuantity(self.value ** power, *new_dims)
    def __neg__(self):
        return PhysicalQuantity(-self.value, *self.dims)
    def exp(self):
        if self.dims != (0, 0, 0):
            raise DimensionalityError(f"exp() requires dimensionless argument, got {self}")
        return PhysicalQuantity(math.exp(self.value), 0, 0, 0)
"""

@router.post("/api/validate/formula")
async def validate_formula(payload: dict):
    text = payload.get("text", "")
    formulas_list = payload.get("formulas", [])

    # Extract from text field
    extracted = []
    if text:
        m = re.search(r'PYTHON_FORMULA:\s*(.+)', text)
        if m:
            extracted.append(m.group(1).strip())

    # Use formulas list if provided
    if formulas_list:
        extracted.extend(formulas_list)

    if not extracted:
        raise HTTPException(400, "No formulas found")

    code = PQ_CODE + """
import json
symbols = {
    "u": PhysicalQuantity(2.0, m=1, kg=0, s=-1),
    "omega": PhysicalQuantity(4.0, m=0, kg=0, s=-1),
    "mu": PhysicalQuantity(0.001, m=-1, kg=1, s=-1),
    "S_ij": PhysicalQuantity(5.0, m=0, kg=0, s=-1),
    "du_i_dx_j": PhysicalQuantity(1.0, m=0, kg=0, s=-1),
    "du_j_dx_i": PhysicalQuantity(1.0, m=0, kg=0, s=-1),
    "du_k_dx_k": PhysicalQuantity(1.0, m=0, kg=0, s=-1),
    "delta_ij": PhysicalQuantity(1.0, m=0, kg=0, s=0),
    "lmbda": PhysicalQuantity(0.001, m=-1, kg=1, s=-1),
    "tau_ij": PhysicalQuantity(1.0, m=-1, kg=1, s=-2),
    "H": PhysicalQuantity(8.0, m=3, kg=0, s=-2),
    "nu": PhysicalQuantity(0.001, m=2, kg=0, s=-1),
}
formulas = """ + json.dumps(extracted) + """
results = []
for f in formulas:
    try:
        namespace = dict(symbols)
        namespace["exp"] = lambda x: x.exp() if isinstance(x, PhysicalQuantity) else math.exp(x)
        namespace["__builtins__"] = {}
        result = eval(f, namespace)
        if isinstance(result, PhysicalQuantity):
            dims = result.dims
            dim_str = f"m^{dims[0]} kg^{dims[1]} s^{dims[2]}"
            results.append({"formula": f, "valid": True, "dimensions": dim_str, "message": "OK"})
        else:
            results.append({"formula": f, "valid": False, "dimensions": None, "message": "Result is not a PhysicalQuantity"})
    except DimensionalityError as e:
        results.append({"formula": f, "valid": False, "dimensions": None, "message": str(e)})
    except Exception as e:
        results.append({"formula": f, "valid": False, "dimensions": None, "message": str(e)[:200]})
print(json.dumps(results))
"""

    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(f"{SANDBOX_URL}/run",
            json={"code": code, "language": "python"})
        data = r.json()
        if data.get("status") == "success":
            return json.loads(data["stdout"])
        return {"error": data.get("stderr", "Sandbox failed")[:500]}
