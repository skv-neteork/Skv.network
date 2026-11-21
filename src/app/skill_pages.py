"""Page a skill body so one cube response stays under the MCP serializer cap.

Each page is an exact slice of skill_md. The caller concatenates page 1 through
skill_pages. A page never contains a trim marker. Worst-case JSON escaping
(every character a quote) plus about 2000 characters of the other fields stays
under 9000, which is the cap the public path can carry.
"""
RAW_PAGE = 3000
RESP_LIMIT = 9000
OVERHEAD = 2000


def _slice_len():
    budget = RESP_LIMIT - OVERHEAD
    worst = max(1, (budget - 2) // 2)
    return min(RAW_PAGE, worst)


def page_skill(text, page=1):
    """One exact slice plus the fields a caller needs to walk the rest."""
    text = text or ""
    size = _slice_len()
    pages = 1 if not text else (len(text) + size - 1) // size
    try:
        page = int(page or 1)
    except (TypeError, ValueError):
        page = 1
    if page < 1:
        page = 1
    if page > pages:
        page = pages
    start = (page - 1) * size
    chunk = text[start:start + size]
    out = {
        "skill_md": chunk,
        "skill_page": page,
        "skill_pages": pages,
        "skill_md_len": len(text),
        "skill_complete": chunk == text,
        "skill_next": page + 1 if page < pages else None,
    }
    if pages > 1:
        out["hint"] = "concatenate skill_md from page=1 through skill_pages"
    return out
