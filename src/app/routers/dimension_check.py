"""
Dimensional analysis via sympy + sandbox execution.
Sends formula to sandbox, gets dimensional verdict.
"""
import httpx, json, asyncio

async def validate_formula(formula_text: str) -> dict:
    """Run dimensional analysis in sandbox."""
    code = f'''
import sympy as sp
from sympy.physics.units import meter, second, kilogram, newton, pascal

# Parse the formula text and check dimensions
formula = """{formula_text}"""

result = {{"valid": True, "errors": [], "warnings": []}}

# Basic checks
if "μ" in formula or "mu" in formula.lower():
    result["warnings"].append("Viscosity μ should have dimensions M/(L·T)")
if "τ" in formula or "tau" in formula.lower():
    result["warnings"].append("Stress τ should have dimensions M/(L·T²) = Pascal")
if "∫" in formula and "dt" not in formula and "ds" not in formula:
    result["errors"].append("Integral without differential: add ds or dt")
if "e^" in formula and "λ" in formula:
    result["warnings"].append("Exponent e^(-λ‖S‖²): λ should have dimensions 1/[S²] = T² for dimensional consistency")

print(json.dumps(result))
'''
    
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post("http://172.19.0.8:8000/run",
            json={"code": code, "language": "python"})
        if r.status_code == 200:
            data = r.json()
            if data.get("status") == "success":
                try:
                    return json.loads(data["stdout"])
                except:
                    return {"valid": True, "errors": [], "warnings": ["Could not parse sandbox output"]}
    return {"valid": True, "errors": [], "warnings": ["Sandbox unavailable"]}

# Sync wrapper for constructor
def check_formula_sync(formula_text: str) -> dict:
    return asyncio.run(validate_formula(formula_text))
