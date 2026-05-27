import json, re
from typing import Dict, List

REQUIRED_FIELDS = ['cube_id', 'title', 'rules', 'trigger_intent']

def validate_cube(cube: Dict) -> Dict:
    """Validate cube and return errors/warnings/suggestions."""
    errors, warnings, suggestions = [], [], []
    cid = cube.get('cube_id', 'unknown')
    
    # Required fields
    for f in REQUIRED_FIELDS:
        if f not in cube:
            errors.append(f"Missing required field: {f}")
    if errors:
        return {"cube_id": cid, "is_valid": False, "errors": errors, "warnings": warnings, "suggestions": suggestions}
    
    # cube_id format
    if not re.match(r'^[a-z0-9_\-]+$', cid):
        errors.append("cube_id must be lowercase alphanumeric with underscores/hyphens")
    
    # Rules
    rules = cube.get('rules', [])
    if not isinstance(rules, list) or len(rules) == 0:
        errors.append("rules must be a non-empty list")
    else:
        for i, rule in enumerate(rules):
            if not any(rule.strip().startswith(kw) for kw in ['MUST', 'PROHIBITED', 'WARNING', 'SHALL']):
                warnings.append(f"Rule {i+1} doesn't start with MUST/PROHIBITED/WARNING/SHALL")
    
    # trigger_intent
    triggers = cube.get('trigger_intent', [])
    if not isinstance(triggers, list):
        errors.append("trigger_intent must be a list")
    elif len(triggers) < 3:
        suggestions.append("Add more trigger_intent keywords (min 3 recommended)")
    
    # Priority
    priority = cube.get('priority')
    if priority is not None and priority not in [1, 2, 3, 4]:
        errors.append("priority must be 1, 2, 3, or 4")
    
    return {
        "cube_id": cid,
        "is_valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "suggestions": suggestions
    }
