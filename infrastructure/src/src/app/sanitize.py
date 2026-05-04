"""Prompt Injection Protection for SKV."""

FORBIDDEN_PATTERNS = [
    "ignore all previous instructions",
    "ignore previous instructions",
    "you are now",
    "system prompt",
    "system message",
    "you are a",
    "forget everything",
    "disregard",
    "override",
]

def sanitize_cube_text(text: str) -> str:
    """Проверяет текст кубика на попытку взлома промта."""
    text_lower = text.lower()
    for pattern in FORBIDDEN_PATTERNS:
        if pattern in text_lower:
            return f"[BLOCKED: contains forbidden pattern '{pattern}']"
    return text

def sanitize_rules(rules: list) -> list:
    """Фильтрует правила кубика."""
    return [sanitize_cube_text(rule) for rule in rules if sanitize_cube_text(rule) != "[BLOCKED]"]

def is_safe_cube(cube_content: dict) -> bool:
    """Проверяет, безопасен ли кубик для инъекции в промт."""
    if not isinstance(cube_content, dict):
        return True
    rules = cube_content.get("rules", [])
    for rule in rules:
        if isinstance(rule, str) and sanitize_cube_text(rule).startswith("[BLOCKED"):
            return False
    return True
