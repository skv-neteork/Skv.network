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



# --- EQ-12 v2 (2026-11-02): non-destructive mode -------------------------------------------
# Ablation (abl_eq*.py, q2s eval): stripping names from the vector query and boosting x3 every
# candidate that contains an extracted "entity" cost locomo -15 h@5 / xling -7 / real_ru -6.
# Frequent names (speakers) are not discriminative, sentence-initial words ("Сколько", "Which")
# were taken as entities, and trailing "?" broke the substring match. Mode "nd" keeps the query
# intact for the vector search; exact terms only ADD signal: a passage-level exact-token rerank
# (passage_rr) and an optional DF-gated entity boost (factor 1.0 = off by default).
#   eq12_mode: "nd" (default) | "legacy" (old destructive behaviour) | "off"
#   env SKV_EQ12_MODE overrides q2s.json; eq12_exact_boost (1.0), eq12_exact_df (0.01),
#   memory_passage_rr_lam (0.1; 0 = off)
import os as _os
import sqlite3 as _sqlite3

_PUNCT = re.compile(r"^[\"'«»“”(\[{<]+|[\"'«»“”)\]}>?!.,;:]+$")


def _cfg() -> dict:
    try:
        from app import q2s as _q
        return _q.cfg()
    except Exception:
        return {}


def mode() -> str:
    m = (_os.environ.get("SKV_EQ12_MODE") or _cfg().get("eq12_mode") or "nd").strip().lower()
    return m if m in ("nd", "legacy", "off") else "nd"


def exact_terms(query: str) -> List[str]:
    """Exact-term spans: capitalized words not at sentence start (punctuation / 's stripped),
    ALLCAPS, tokens with digits or / _, Latin terms in a Cyrillic query, dates."""
    out = []
    cyr = bool(_RU.search(query or ""))
    for i, w in enumerate((query or "").split()):
        t = _PUNCT.sub("", _PUNCT.sub("", w))
        t = re.sub(r"['’]s$", "", t)
        if len(t) < 2 or t.lower() in _QWORDS:
            continue
        if (re.search(r"\d|/|_", t) or (cyr and re.fullmatch(r"[A-Za-z][\w.-]*", t))
                or (i > 0 and t[:1].isupper()) or t.isupper()):
            out.append(t)
    out += [m.group(0) for m in _DATE_RE.finditer(query or "")]
    return list(dict.fromkeys(out))


def _doc_freq(uid: str, terms: List[str]) -> dict:
    from app import search_v2 as V
    res = {}
    conn = _sqlite3.connect(V._db(uid), timeout=10)
    try:
        n = conn.execute("SELECT count(*) FROM events_fts_stem").fetchone()[0] or 1
        for t in terms:
            s = V.stem_text(t).replace('"', "")
            res[t] = (conn.execute("SELECT count(*) FROM events_fts_stem WHERE events_fts_stem MATCH ?",
                                   ('"%s"' % s,)).fetchone()[0] / n) if s else 1.0
    finally:
        conn.close()
    return res


def exact_signal(uid: str, query: str, results: list) -> list:
    """results: list of dicts with event_id/score (fused order). Never drops items."""
    c = _cfg()
    f = float(c.get("eq12_exact_boost", 1.0))
    if f != 1.0 and results:
        terms = exact_terms(query)
        if terms:
            dfm = _doc_freq(uid, terms)
            rare = [Entity(t, "name", 0, 0) for t in terms if 0 < dfm.get(t, 1.0) <= float(c.get("eq12_exact_df", 0.01))]
            if rare:
                by = {r["event_id"]: r for r in results}
                out = []
                for eid, sc in boost_by_entities(uid, [(r["event_id"], r["score"]) for r in results], rare, f):
                    if eid in by:
                        by[eid]["score"] = round(sc, 5); out.append(by.pop(eid))
                results = out + list(by.values())
    lam = float(c.get("memory_passage_rr_lam", 0.1))
    if lam > 0 and len(results) > 1:
        from app import passage_rr as _prr
        results = _prr.rerank(uid, query, results, dict(c, passage_rr_lam=lam))
    return results
