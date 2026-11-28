"""Event note: search_as and draft_summary live in essence. Raw dialogue stays.

The headline is the first lines. The vector text is that headline plus the raw
start, trimmed to the embedder's token limit. The raw side is what gets cut.
"""
import json
import os
import re
import sqlite3

_TOKENIZER = os.environ.get(
    "SKV_MML_TOKENIZER",
    "/data/skv/models/models--Qdrant--paraphrase-multilingual-MiniLM-L12-v2-onnx-Q"
    "/snapshots/faf4aa4225822f3bc6376869cb1164e8e3feedd0/tokenizer.json",
)
_VOCAB = None
_STATS = "/data/skv/metadata_store/search_as_stats.db"


def headline(essence):
    """'<search_as> -> <draft_summary>' from the note lines. Empty when there is no note."""
    gloss = outcome = ""
    for line in (essence or "").split("\n"):
        if line.startswith("» ") and not gloss:
            gloss = line[2:].strip()
        elif line.startswith("→ ") and not outcome:
            outcome = line[2:].strip()
    if gloss and outcome:
        return gloss + " -> " + outcome
    return gloss or outcome


def essence_prepend(old, search_as):
    """Put the retelling on the first line. An existing retelling is left as it is."""
    note = re.sub(r"\s+", " ", (search_as or "").strip())[:160]
    if not note or note == "-":
        return old or ""
    line = "» " + note
    old = old or ""
    if old.startswith("» "):
        return old
    return (line + "\n" + old).strip() if old else line


def essence_outcome(old, draft_summary):
    """Second line of the note. The earlier essence text stays under it."""
    note = re.sub(r"\s+", " ", (draft_summary or "").strip())[:160]
    if not note:
        return old or ""
    line = "→ " + note
    lines = (old or "").split("\n") if old else []
    out = []
    placed = False
    for ln in lines:
        if ln.startswith("→ "):
            if not placed:
                out.append(line)
                placed = True
            continue
        out.append(ln)
        if ln.startswith("» ") and not placed:
            out.append(line)
            placed = True
    if not placed:
        out.insert(0, line)
    return "\n".join(x for x in out if x is not None).strip()


def fts_body(essence, raw):
    """Note plus the full raw dialogue. No note: the raw text alone, as before."""
    note = headline(essence)
    raw = raw or ""
    if not note:
        return raw
    return note + "\n" + raw


def _vocab():
    global _VOCAB
    if _VOCAB is not None:
        return _VOCAB
    if not os.path.isfile(_TOKENIZER):
        _VOCAB = {}
        return _VOCAB
    try:
        with open(_TOKENIZER, encoding="utf-8") as fh:
            data = json.load(fh)
        _VOCAB = {tok: float(score) for tok, score in (data.get("model") or {}).get("vocab") or [] if tok}
    except Exception:
        _VOCAB = {}
    return _VOCAB


def _piece_count(word, vocab):
    n = len(word)
    if n <= 0:
        return 0
    neg = -1e30
    best = [neg] * (n + 1)
    count = [0] * (n + 1)
    best[0] = 0.0
    for i in range(n):
        if best[i] <= neg / 2:
            continue
        upper = min(n, i + 32)
        for j in range(i + 1, upper + 1):
            score = vocab.get(word[i:j])
            if score is None:
                continue
            val = best[i] + score
            if val > best[j]:
                best[j] = val
                count[j] = count[i] + 1
    if best[n] > neg / 2 and count[n]:
        return count[n]
    return max(1, n)


def token_count(text):
    """MiniLM unigram count when the vocab file is present. Otherwise one token per word."""
    vocab = _vocab()
    text = text or ""
    if not vocab:
        parts = text.split()
        return len(parts) if parts else (1 if text else 0)
    total = 0
    for part in re.findall(r"\S+", text):
        total += _piece_count("▁" + part, vocab)
    return total


def vector_text(essence, raw, limit=128, count=None):
    """'[note]\\n' plus the raw start. Events with no note stay the raw start.

    The note is never trimmed. The raw side is cut so the total fits `limit` tokens.
    """
    raw = raw or ""
    note = headline(essence)
    if not note:
        return raw[:1000]
    prefix = "[" + note + "]\n"
    counter = count or token_count
    if counter(prefix) >= int(limit or 128):
        return prefix
    lo, hi = 0, len(raw)
    best = prefix
    while lo <= hi:
        mid = (lo + hi) // 2
        cand = prefix + raw[:mid]
        if counter(cand) <= int(limit or 128):
            best = cand
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def skeleton_lines(text):
    """Headline lines already stored on events. Empty when the material has none."""
    out = []
    for raw in (text or "").splitlines():
        line = " ".join(raw.split()).strip()
        if line.startswith("» ") or line.startswith("→ "):
            out.append(line[:200])
        if len(out) >= 8:
            break
    return out


def refresh_fts(conn, event_id):
    """One events_fts_stem row: note plus the full raw. Missing table: no change."""
    if conn is None or not event_id:
        return False
    try:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='events_fts_stem'").fetchone():
            return False
        row = conn.execute(
            "SELECT coalesce(essence,''), coalesce(raw_dialogue,'') FROM event_metadata WHERE event_id=?",
            (event_id,),
        ).fetchone()
    except sqlite3.Error:
        return False
    if not row:
        return False
    try:
        from app.search_v2 import stem_text
        body = stem_text(fts_body(row[0], row[1]))
    except Exception:
        body = fts_body(row[0], row[1])
    try:
        conn.execute("DELETE FROM events_fts_stem WHERE event_id=?", (event_id,))
        conn.execute("INSERT INTO events_fts_stem(event_id, body) VALUES (?,?)", (event_id, body))
    except sqlite3.Error:
        return False
    return True


def _apply_essence(conn, event_id, new_essence):
    conn.execute("UPDATE event_metadata SET essence=? WHERE event_id=?", (new_essence, event_id))
    refresh_fts(conn, event_id)


def stamp_search_as(path, event_id, search_as):
    """Prepend a good retelling onto one event. Raw dialogue is not rewritten."""
    if not path or not event_id or not (search_as or "").strip():
        return ""
    conn = sqlite3.connect(path, timeout=30)
    try:
        row = conn.execute("SELECT coalesce(essence,'') FROM event_metadata WHERE event_id=?", (event_id,)).fetchone()
        if not row:
            return ""
        updated = essence_prepend(row[0], search_as)
        if updated == row[0]:
            return updated
        _apply_essence(conn, event_id, updated)
        conn.commit()
        return updated
    except sqlite3.Error:
        return ""
    finally:
        conn.close()


def stamp_outcome(path, event_id, draft_summary, reembed=True):
    """Store the outcome line on one event and re-embed that one vector."""
    if not path or not event_id or not (draft_summary or "").strip():
        return ""
    conn = sqlite3.connect(path, timeout=30)
    try:
        row = conn.execute(
            "SELECT coalesce(essence,''), coalesce(raw_dialogue,'') FROM event_metadata WHERE event_id=?",
            (event_id,),
        ).fetchone()
        if not row:
            return ""
        updated = essence_outcome(row[0], draft_summary)
        _apply_essence(conn, event_id, updated)
        conn.commit()
        raw = row[1]
    except sqlite3.Error:
        return ""
    finally:
        conn.close()
    if reembed:
        _reembed(path, event_id, updated, raw)
    return updated


def _reembed(path, event_id, essence, raw):
    try:
        from app import semantic
        user = event_id.split("::", 1)[0] if "::" in event_id else ""
        if not user:
            name = os.path.basename(path).replace(".db", "")
            user = name
        semantic.reembed_one(user, event_id, vector_text(essence, raw))
    except Exception as exc:
        print("[gloss_note] reembed skipped: %s" % type(exc).__name__, flush=True)


def bump(agent, kind, path=None):
    """Count search_as_filled / dash_ok / dash_rejected / missed. Returns the new total."""
    kind = (kind or "").strip()
    if kind not in ("filled", "dash_ok", "dash_rejected", "missed"):
        return 0
    agent = re.sub(r"[^A-Za-z0-9_.:-]", "", agent or "anon")[:40] or "anon"
    path = path or _STATS
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        conn = sqlite3.connect(path, timeout=10)
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS search_as_stats (agent TEXT, kind TEXT, n INTEGER, PRIMARY KEY(agent, kind))"
            )
            conn.execute(
                "INSERT INTO search_as_stats (agent, kind, n) VALUES (?,?,1) "
                "ON CONFLICT(agent, kind) DO UPDATE SET n=n+1",
                (agent, kind),
            )
            row = conn.execute("SELECT n FROM search_as_stats WHERE agent=? AND kind=?", (agent, kind)).fetchone()
            conn.commit()
            return int(row[0]) if row else 0
        finally:
            conn.close()
    except sqlite3.Error:
        return 0


def count_of(agent, kind, path=None):
    agent = re.sub(r"[^A-Za-z0-9_.:-]", "", agent or "anon")[:40] or "anon"
    path = path or _STATS
    try:
        conn = sqlite3.connect(path, timeout=5)
        try:
            row = conn.execute(
                "SELECT n FROM search_as_stats WHERE agent=? AND kind=?",
                (agent, kind),
            ).fetchone()
            return int(row[0]) if row else 0
        finally:
            conn.close()
    except sqlite3.Error:
        return 0
