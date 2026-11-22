"""One short tool duty when a past-work question is not already answered by the facts."""
import re

_PAST = re.compile(
    r"(мы\s+делали|помнишь|обсуждали|вчера|на\s+прошлой|did\s+we|do\s+you\s+remember|have\s+we|we\s+discussed|yesterday)",
    re.I,
)
_DID = re.compile(r"(мы\s+делали|сделали\s+ли|did\s+we|have\s+we(\s+done)?)", re.I)
_KNOW = re.compile(r"(как\s+сделать|how\s+do\s+i|know-how|лайфхак|lifehack|рецепт)", re.I)

_LINE = (
    "Search yourself before answering: memory_recall_later(query, search_as=[statement in the base language; keep names and the date]) "
    "or memory_search(lines=all). Poll memory_recall_status before saying you do not know."
)
_DID_LINE = (
    "Search yourself before answering: memory_recall_later(query, search_as=[statement of the event]) "
    "and check the board task plus the git commit. Poll memory_recall_status before saying you do not know."
)
_KNOW_LINE = (
    "Search yourself before answering: cube_search, then cube_get or cube_install for the reusable know-how."
)


def past_question(text):
    return bool(_PAST.search(text or ""))


def facts_weak(message, facts):
    """True when the fast facts do not share the question's topic."""
    try:
        from app.turn_context import on_topic
    except Exception:
        return True
    if not facts:
        return True
    parts = []
    for f in facts:
        if isinstance(f, dict):
            parts.append(str(f.get("fact") or f.get("summary") or ""))
        elif isinstance(f, str):
            parts.append(f)
    blob = " ".join(parts)
    if not blob.strip():
        return True
    return not on_topic(message or "", blob)


def duty_line(message, facts):
    """One line, or None. At most one tool duty."""
    if not past_question(message):
        return None
    if not facts_weak(message, facts):
        return None
    if _DID.search(message or ""):
        return _DID_LINE
    if _KNOW.search(message or ""):
        return _KNOW_LINE
    return _LINE


def apply(result, message, facts):
    """Attach tool_duty when due. Never raises. Does not replace an existing line."""
    if not isinstance(result, dict) or result.get("tool_duty"):
        return result
    try:
        line = duty_line(message, facts)
    except Exception:
        return result
    if not line:
        return result
    result["tool_duty"] = line
    duties = list(result.get("duties") or [])
    if line not in duties:
        duties.insert(0, line)
        result["duties"] = duties
    return result
