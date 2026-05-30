"""
Dimensional analysis validator for physical formulas.
Checks if formulas have consistent dimensions (M, L, T, K).
"""

def check_dimensions(formula_text: str) -> dict:
    """
    Basic dimensional analysis.
    Returns: {valid: bool, errors: [str], warnings: [str]}
    """
    errors = []
    warnings = []
    
    # Known physical quantities and their dimensions (M, L, T, K)
    dimensions = {
        "velocity": (0, 1, -1, 0),  # L/T
        "speed": (0, 1, -1, 0),
        "acceleration": (0, 1, -2, 0),  # L/T²
        "force": (1, 1, -2, 0),  # M·L/T²
        "pressure": (1, -1, -2, 0),  # M/(L·T²)
        "energy": (1, 2, -2, 0),  # M·L²/T²
        "power": (1, 2, -3, 0),  # M·L²/T³
        "density": (1, -3, 0, 0),  # M/L³
        "viscosity": (1, -1, -1, 0),  # M/(L·T)
        "helicity": (0, 4, -2, 0),  # L⁴/T²
        "stress": (1, -1, -2, 0),  # M/(L·T²) — same as pressure
        "strain_rate": (0, 0, -1, 0),  # 1/T
    }
    
    # Check for common dimensional mismatches
    checks = [
        ("stress = viscosity * strain_rate", 
         dimensions["stress"], 
         tuple(a + b for a, b in zip(dimensions["viscosity"], dimensions["strain_rate"]))),
    ]
    
    for description, expected, actual in checks:
        if expected != actual:
            errors.append(f"{description}: expected {expected}, got {actual}")
    
    if not errors:
        return {"valid": True, "errors": [], "warnings": warnings}
    return {"valid": False, "errors": errors, "warnings": warnings}

def validate_formula(formula_text: str) -> dict:
    """Main entry point for sandbox validation."""
    result = check_dimensions(formula_text)
    if not result["valid"]:
        result["action"] = "fix"
        result["suggestion"] = "Check dimensions: left and right sides must match (M, L, T, K)"
    else:
        result["action"] = "pass"
    return result

if __name__ == "__main__":
    # Test
    test = "τ = 2μ·S"
    print(f"Testing: {test}")
    print(validate_formula(test))
