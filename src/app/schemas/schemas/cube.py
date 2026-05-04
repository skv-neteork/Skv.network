"""Object model for SKV cubes."""
from pydantic import BaseModel, Field, validator
from typing import List, Optional
from datetime import datetime

class RuleObject(BaseModel):
    id: Optional[str] = None
    type: str = "instruction"
    action: str
    priority: int = Field(default=5, ge=1, le=10)
    target: Optional[str] = None

class CubeObject(BaseModel):
    cube_id: str
    title: str
    cube_type: str = "basic"
    trigger_intent: List[str] = []
    rules: List[RuleObject] = []
    priority: int = Field(default=1, ge=1, le=4)
    version: str = "1.0.0"
    status: str = "verified"
    dependencies: List[str] = []
    conflicts_with: List[str] = []
    rationale: Optional[str] = None
    examples: List[str] = []
    source: Optional[str] = None
    project_ref: Optional[str] = None

def wrap_legacy_cube(cube_data: dict) -> CubeObject:
    rules = cube_data.get("rules", [])
    if rules and isinstance(rules[0], str):
        rules = [RuleObject(id=f"rule_{i+1}", type="instruction", action=r).dict() for i, r in enumerate(rules)]
    return CubeObject(
        cube_id=cube_data.get("cube_id", ""),
        title=cube_data.get("title", "Untitled"),
        cube_type=cube_data.get("type", "basic"),
        trigger_intent=cube_data.get("trigger_intent", []),
        rules=rules,
        priority=cube_data.get("priority", 3),
        version=cube_data.get("version", "1.0.0"),
        status=cube_data.get("status", "community"),
        dependencies=cube_data.get("dependencies", []),
        conflicts_with=cube_data.get("conflicts_with", []),
        rationale=cube_data.get("rationale", ""),
        examples=cube_data.get("examples", []),
        source=cube_data.get("source", ""),
        project_ref=cube_data.get("project_ref", "")
    )
