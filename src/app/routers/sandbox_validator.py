"""
Sandbox-based dimensional analysis.
Runs PhysicalQuantity validation in isolated Docker container.
"""
import httpx, json, asyncio

SANDBOX_URL = "http://172.19.0.8:8000"

async def validate_dimensions(latex_formulas: list, task_context: str = "") -> dict:
    """Send formulas to sandbox for dimensional analysis."""
    
    code = f'''
import sys
sys.path.insert(0, "/app/validators")
from physical_quantity import PhysicalQuantity, DimensionalityError
from dimensions import LaTeXDimensionValidator
import json

symbols = {{
    "u": PhysicalQuantity(2.0, m=1, kg=0, s=-1),
    "omega": PhysicalQuantity(4.0, m=0, kg=0, s=-1),
    "mu": PhysicalQuantity(0.001, m=-1, kg=1, s=-1),
    "dV": PhysicalQuantity(1.0, m=3, kg=0, s=0),
    "S_ij": PhysicalQuantity(5.0, m=0, kg=0, s=-1),
    "H": PhysicalQuantity(8.0, m=3, kg=0, s=-2),
    "nu": PhysicalQuantity(0.001, m=2, kg=0, s=-1),
}}

validator = LaTeXDimensionValidator(symbols)
formulas = {json.dumps(latex_formulas)}
results = []

for f in formulas:
    ok, res, msg = validator.validate(f)
    results.append({{
        "formula": f,
        "valid": ok,
        "result": str(res) if ok else None,
        "message": msg
    }})

print(json.dumps(results))
'''
    
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(f"{SANDBOX_URL}/run",
            json={"code": code, "language": "python"})
        if r.status_code == 200:
            data = r.json()
            if data.get("status") == "success":
                return json.loads(data["stdout"])
    return [{"valid": False, "message": "Sandbox unavailable"}]
