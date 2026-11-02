"""EQ-12 search reformulation (2026-11-01).

Server-side reformulation of user queries before memory search.
- Proper nouns / specific entities (names, places, orgs, dates) → exact FTS match
- Residual narrative (verbs, actions, adjectives, concepts) → vector search
- Language-aware: detects query language

Based on deep consultation #11. Practical implementation without heavy NER.
"""
import re
from dataclasses import dataclass, field
from typing import Optional, List, Tuple

_QWORDS = set("""
when what where who how why did does is are was were do the a an
of to in on at for with by from as not no yes
когда что где кто как почему какой какая какое какие
это эта этот эти тот та то те
""".split())

_DATE_RE = re.compile(
    r"(?P<iso>\d{4}-\d{2}-\d{2})"
    r"|(?P<eu>\d{1,2}\.\d{1,2}\.\d{2,4})"
    r"|(?P<long>\d{1,2}\s+(?:января|февраля|марта|апреля|мая|июня|июля|августа|"
    r"сентября|октября|ноября|декабря|January|February|March|April|May|June|"
    r"July|August|September|October|November|December)\s+\d{4})",
    re.IGNORECASE,
)

_RU = re.compile(r"[а-яё]", re.IGNORECASE)
_EN = re.compile(r"[a-z]", re.IGNORECASE)


@dataclass(frozen=True)
class Entity:
    text: str
    kind: str
    start: int
    end: int
    iso_date: Optional[str] = None


@dataclass
class Reformulated:
    original: str
    entities: List[Entity] = field(default_factory=list)
    narrative: str = ""
    lang: str = "en"
    target_lang: str = "en"

    @property
    def entity_texts(self) -> List[str]:
        return [e.text for e in self.entities if e.kind != "date"]

    @property
    def dates(self) -> List[str]:
        return [e.iso_date or e.text for e in self.entities if e.kind == "date"]

    @property
    def has_entities(self) -> bool:
        return bool(self.entities)


def detect_lang(text: str) -> str:
    ru = len(_RU.findall(text or ""))
    en = len(_EN.findall(text or ""))
    if ru > en * 1.5:
        return "ru"
    if en > ru * 1.5:
        return "en"
    if ru and en:
        return "mixed"
    return "en" if en else "ru" if ru else "en"


def _normalize_date(m: re.Match) -> Optional[str]:
    if m.group("iso"):
        return m.group("iso")
    if m.group("eu"):
        parts = m.group("eu").split(".")
        if len(parts) == 3:
            d, mo, y = parts
            y = y if len(y) == 4 else ("20" + y if int(y) < 50 else "19" + y)
            return f"{y}-{int(mo):02d}-{int(d):02d}"
    return None


def extract_entities(query: str) -> List[Entity]:
    """Extract proper-noun spans and dates from query.
    
    Rules:
    - Consecutive capitalized tokens (not question words) form a span
    - Dates via regex
    - Does NOT extract common nouns
    """
    entities: List[Entity] = []
    seen = set()

    for m in _DATE_RE.finditer(query):
        iso = _normalize_date(m)
        text = m.group(0)
        key = (m.start(), m.end())
        if key not in seen:
            seen.add(key)
            entities.append(Entity(text, "date", m.start(), m.end(), iso))

    words = query.split()
    i = 0
    while i < len(words):
        w = words[i]
        if not w[:1].isupper() or w.lower() in _QWORDS or len(w) < 2:
            i += 1
            continue
        span = [w]
        j = i + 1
        while j < len(words):
            nw = words[j]
            if nw[:1].isupper() and nw.lower() not in _QWORDS and len(nw) > 1:
                span.append(nw)
                j += 1
            else:
                break
        text = " ".join(span)
        pos = query.find(text)
        if pos >= 0 and (pos, pos + len(text)) not in seen:
            seen.add((pos, pos + len(text)))
            entities.append(Entity(text, "name", pos, pos + len(text)))
        i = j

    entities.sort(key=lambda e: e.start)
    return entities


def reformulate(query: str, memory_lang: Optional[str] = None) -> Reformulated:
    """Reformulate query into entities (exact) + narrative (vector)."""
    query = (query or "").strip()
    if not query:
        return Reformulated(original="", lang="en")

    lang = detect_lang(query)
    target = memory_lang or lang

    entities = extract_entities(query)

    narrative = query
    for e in sorted(entities, key=lambda x: -x.start):
        narrative = narrative[:e.start] + " " + narrative[e.end:]
    narrative = re.sub(r"\s+", " ", narrative).strip()
    narrative = re.sub(
        r"^(when|what|where|who|how|why|did|does|is|are|was|were|do|"
        r"когда|что|где|кто|как|почему)\s+",
        "", narrative, flags=re.IGNORECASE
    ).strip()

    return Reformulated(
        original=query,
        entities=entities,
        narrative=narrative,
        lang=lang,
        target_lang=target,
    )


def fts_entity_query(entities: List[Entity]) -> Optional[str]:
    """Build FTS5 OR query for entity texts. Returns None if no entities."""
    phrases = []
    for e in entities:
        if e.kind == "date":
            continue
        esc = e.text.replace('"', '""')
        phrases.append(f'"{esc}"')
    if not phrases:
        return None
    return " OR ".join(phrases)


def boost_by_entities(uid: str, results: List[Tuple[str, float]],
                      entities: List[Entity], factor: float = 3.0) -> List[Tuple[str, float]]:
    """Boost results that contain any of the entity texts."""
    if not entities or not results:
        return results
    texts = [e.text.lower() for e in entities if e.kind != "date"]
    if not texts:
        return results
    try:
        import sqlite3, os
        from app.semantic import BASE_DIR, account_name
        db = os.path.join(BASE_DIR, account_name(uid) + ".db")
        conn = sqlite3.connect(db, timeout=10)
        ids = [e for e, _ in results]
        qmarks = ",".join("?" * len(ids))
        rows = conn.execute(
            f"SELECT event_id, raw_dialogue FROM event_metadata WHERE event_id IN ({qmarks})",
            ids
        ).fetchall()
        conn.close()
    except Exception:
        return results
    body = {e: (r or "").lower() for e, r in rows}
    out = []
    for eid, sc in results:
        b = body.get(eid, "")
        if any(t in b for t in texts):
            sc = sc * factor
        out.append((eid, sc))
    out.sort(key=lambda x: -x[1])
    return out
