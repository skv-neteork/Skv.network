"""Local 8/8/8 memory snapshot.

One UTF-8 document: about 8000 estimated tokens of the newest raw turns,
8000 of older L1 summaries, 8000 of still older L2 blocks. Layer ranges are
event rowids and do not overlap. A record is kept whole or left out.
Constitution and profile are included in full. Critical marks are not a
separate list: the marks whose source events fall inside the shipped L2, L1 and
raw windows are written as short "CRITICAL:" heading lines inside those sections
(capped; the rest is counted). The board and tasks are one short list of open
items (id | status | title | waiting_for). The access registry is one counter
line; the full list stays behind the profile page and the keys tools.

Token figures use memory_v2.est_tokens. That is an estimate, not a tokenizer count.
This does not change the HTTP bootstrap, which stays size-capped for the network stall.
step_zero serves this same document as pages. The pages join back to the document.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from app.memory_v2 import est_tokens, mask_text

BUDGET = 8000
TOKEN_METHOD = {
    "method": "memory_v2.est_tokens",
    "exact": False,
    "formula": "ceil(ascii_chars/4 + non_ascii_chars/2.5)",
    "note": "Estimate used by SKV. Not a model tokenizer count.",
}
SHARED_DB = "/data/skv/metadata_store/shared_master.db"
USER_DB_DIR = "/data/skv/metadata_store"

_EXTRA_SECRET = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S), "[private key masked]"),
    (re.compile(r"\bre_[A-Za-z0-9]{10,}\b"), "[resend token masked]"),
    (re.compile(r"\b(?:postgres|mysql|mongodb)://\S+"), "[db url masked]"),
    (re.compile(r"(?i)\b(ssh_pass|private[_-]?key)(\s*[:=]\s*)([\"']?)([^\s\"',;]{6,})"),
     lambda m: m.group(1) + m.group(2) + m.group(3) + "[masked]"),
]
_LEAK = [
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("sk_key", re.compile(r"\bsk_[A-Za-z0-9]{16,}\b")),
    ("github_token", re.compile(r"\b(ghp|gho|ghs|github_pat)_[A-Za-z0-9_]{20,}\b")),
    ("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("aws_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("bearer", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{16,}")),
    ("pza_key", re.compile(r"\bpza_[A-Za-z0-9_\-]{8,}")),
    ("resend_key", re.compile(r"\bre_[A-Za-z0-9]{10,}\b")),
    ("db_url", re.compile(r"\b(?:postgres|mysql|mongodb)://\S+")),
    ("assigned_secret", re.compile(
        r"(?i)\b(api[_-]?key|apikey|password|passwd|пароль|secret|token|ssh_pass|private[_-]?key)(\s*[:=]\s*)([\"']?)([^\s\"',;\[]{6,})")),
]


def account_db(user_id: str) -> str:
    name = "".join(c for c in (user_id or "") if c.isalnum() or c in ("_", "-"))
    return os.path.join(USER_DB_DIR, name + ".db")


def mask(text: str) -> Tuple[str, bool]:
    src = text or ""
    out = mask_text(src)
    for rx, rep in _EXTRA_SECRET:
        out = rx.sub(rep, out)
    return out, out != src


def leak_names(text: str) -> List[str]:
    found = []
    for name, rx in _LEAK:
        if rx.search(text or ""):
            found.append(name)
    return found


def _ro(path: str) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)


def _tables(conn: sqlite3.Connection) -> set:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _take(records: Sequence[dict], budget: int) -> dict:
    """Keep a newest-first prefix of whole records. Never cut a record."""
    included, used = [], 0
    excluded = None
    reason = "data_exhausted"
    for rec in records:
        need = int(rec["tokens_estimate"])
        if used + need > budget:
            excluded = {
                "id": rec["id"],
                "tokens_estimate": need,
                "reason": "whole record would pass the budget; left out intact",
            }
            reason = "next_record_exceeds_budget"
            break
        included.append(rec)
        used += need
    return {
        "included": included,
        "tokens_estimate": used,
        "budget": budget,
        "underfill": budget - used,
        "stopped_because": reason,
        "excluded_next": excluded,
    }


def _span(records: Sequence[dict], lo_key: str, hi_key: str) -> dict:
    if not records:
        return {"empty": True, "rowid_min": None, "rowid_max": None, "time_min": None, "time_max": None}
    lo = min(records, key=lambda r: r[lo_key])
    hi = max(records, key=lambda r: r[hi_key])
    return {
        "empty": False,
        "rowid_min": lo[lo_key],
        "rowid_max": hi[hi_key],
        "time_min": lo.get("time_lo") or lo.get("time") or "",
        "time_max": hi.get("time_hi") or hi.get("time") or "",
        "ids": [r["id"] for r in records],
        "count": len(records),
    }


def _raw_records(conn: sqlite3.Connection) -> List[dict]:
    if "event_metadata" not in _tables(conn):
        return []
    out = []
    rows = conn.execute(
        "SELECT rowid, event_id, time_str, raw_dialogue FROM event_metadata "
        "WHERE raw_dialogue IS NOT NULL AND length(trim(raw_dialogue)) > 0 ORDER BY rowid DESC"
    )
    for rowid, eid, ts, raw in rows:
        body, changed = mask(raw)
        out.append({
            "id": str(eid),
            "layer": "raw",
            "rowid": int(rowid),
            "row_lo": int(rowid),
            "row_hi": int(rowid),
            "time": ts or "",
            "time_lo": ts or "",
            "time_hi": ts or "",
            "body": body,
            "secrets_masked": changed,
            "tokens_estimate": est_tokens(body),
        })
    return out


def _l1_records(conn: sqlite3.Connection, before_rowid: Optional[int]) -> Tuple[List[dict], List[str]]:
    if "summary_l1" not in _tables(conn):
        return [], []
    overlap = []
    eligible = []
    rows = conn.execute(
        "SELECT session_id, topic, summary_text, created_at, from_rowid, to_rowid FROM summary_l1"
    )
    for sid, topic, text, created, fr, to in rows:
        if fr is None or to is None:
            overlap.append(str(sid) + ":no_row_range")
            continue
        fr, to = int(fr), int(to)
        if before_rowid is not None and to >= before_rowid:
            overlap.append(str(sid))
            continue
        if fr > to:
            overlap.append(str(sid) + ":inverted")
            continue
        body, changed = mask(text or "")
        eligible.append({
            "id": str(sid),
            "layer": "l1",
            "topic": topic or "",
            "row_lo": fr,
            "row_hi": to,
            "time": created or "",
            "time_lo": created or "",
            "time_hi": created or "",
            "body": body,
            "secrets_masked": changed,
            "tokens_estimate": est_tokens(body),
        })
    eligible.sort(key=lambda r: r["row_hi"], reverse=True)
    overlap.sort()
    return eligible, overlap


def _l2_records(conn: sqlite3.Connection, before_rowid: Optional[int]) -> Tuple[List[dict], dict]:
    notes = {"legacy_map": "absent", "overlap_ids": []}
    if "summary_l2" in _tables(conn):
        n = conn.execute("SELECT count(*) FROM summary_l2").fetchone()[0]
        notes["legacy_map"] = "excluded_no_disjoint_range" if n else "absent"
    if "summary_l2_blocks" not in _tables(conn):
        return [], notes
    eligible = []
    rows = conn.execute(
        "SELECT id, source, period_from, period_to, from_rowid, to_rowid, text FROM summary_l2_blocks"
    )
    for bid, source, p0, p1, fr, to, text in rows:
        if fr is None or to is None:
            notes["overlap_ids"].append(str(bid) + ":no_row_range")
            continue
        fr, to = int(fr), int(to)
        if before_rowid is not None and to >= before_rowid:
            notes["overlap_ids"].append(str(bid))
            continue
        if fr > to:
            notes["overlap_ids"].append(str(bid) + ":inverted")
            continue
        body, changed = mask(text or "")
        eligible.append({
            "id": str(bid),
            "layer": "l2",
            "source": source or "",
            "row_lo": fr,
            "row_hi": to,
            "time": p0 or "",
            "time_lo": p0 or "",
            "time_hi": p1 or "",
            "body": body,
            "secrets_masked": changed,
            "tokens_estimate": est_tokens(body),
        })
    eligible.sort(key=lambda r: r["row_hi"], reverse=True)
    notes["overlap_ids"].sort()
    return eligible, notes


CRITICAL_TITLE_CHARS = 110
CRITICAL_PER_RECORD = 4
CRITICAL_PER_LAYER = 24
OPEN_TITLE_CHARS = 120
OPEN_DONE_STATUSES = ("done", "parked")


def _one_line(text: str, limit: int) -> str:
    line = re.sub(r"\s+", " ", str(text or "")).strip()
    return line if len(line) <= limit else line[: max(1, limit - 1)].rstrip() + "\u2026"


def _short_ev(eid: str) -> str:
    return str(eid or "").split("::")[-1]


def _critical(conn: sqlite3.Connection) -> List[dict]:
    out = []
    if "critical_auto" in _tables(conn):
        for key, kind, value, ctx, eid, ts, hits, *_rest in conn.execute(
            "SELECT key, kind, value, context, event_id, time_str, hits FROM critical_auto"
        ):
            body, changed = mask(f"{kind}: {value}\ncontext: {ctx or ''}\nhits: {hits}")
            title, _c = mask(_one_line(f"{kind}: {value}", CRITICAL_TITLE_CHARS))
            out.append({"id": "auto:" + str(key), "layer": "critical", "time": ts or "", "event_id": eid or "",
                        "title": title, "hits": int(hits or 0), "auto": True,
                        "body": body, "secrets_masked": changed, "tokens_estimate": est_tokens(body)})
    if "event_metadata" in _tables(conn):
        for eid, ts, raw in conn.execute(
            "SELECT event_id, time_str, raw_dialogue FROM event_metadata WHERE raw_dialogue LIKE '%>>>%'"
        ):
            for i, line in enumerate((raw or "").split("\n")):
                if ">>>" not in line:
                    continue
                body, changed = mask(line.strip())
                title, _c = mask(_one_line(re.sub(r"^\s*>>>\s*", "", line), CRITICAL_TITLE_CHARS))
                out.append({"id": f"mark:{eid}:{i}", "layer": "critical", "time": ts or "", "event_id": str(eid),
                            "title": title, "hits": 0, "auto": False,
                            "body": body, "secrets_masked": changed, "tokens_estimate": est_tokens(body)})
    out.sort(key=lambda r: r["id"])
    return out


def _board(conn: sqlite3.Connection) -> List[dict]:
    if "board_items" not in _tables(conn):
        return []
    cols = [r[1] for r in conn.execute("PRAGMA table_info(board_items)")]
    want = [c for c in ("item_id", "kind", "title", "body", "status", "updated_at", "removed",
                        "priority", "parent_id", "waiting_for", "result", "created_at") if c in cols]
    out = []
    for row in conn.execute("SELECT " + ", ".join(want) + " FROM board_items"):
        rec = dict(zip(want, row))
        if rec.get("removed"):
            continue
        body, changed = mask(
            "\n".join(f"{k}: {rec.get(k) or ''}" for k in want if k != "removed")
        )
        out.append({"id": str(rec.get("item_id")), "layer": "board", "kind": rec.get("kind") or "",
                    "status": rec.get("status") or "", "title": rec.get("title") or "",
                    "waiting_for": rec.get("waiting_for") or "", "body": body, "secrets_masked": changed,
                    "tokens_estimate": est_tokens(body)})
    out.sort(key=lambda r: r["id"])
    return out


def _open_items(board: Sequence[dict]) -> Tuple[List[str], int]:
    """One line per open board item. Done and parked items are only counted."""
    lines, closed = [], 0
    for rec in sorted(board, key=lambda r: str(r.get("id") or "")):
        status = str(rec.get("status") or "").strip().lower()
        if status in OPEN_DONE_STATUSES:
            closed += 1
            continue
        title, _c = mask(_one_line(rec.get("title") or "", OPEN_TITLE_CHARS))
        waiting, _c = mask(_one_line(rec.get("waiting_for") or "", 60))
        label = status or str(rec.get("kind") or "item")
        lines.append("%s | %s | %s | %s" % (str(rec.get("id") or "").replace("|", "/"), label, title.replace("|", "/"), waiting.replace("|", "/")))
    return lines, closed


def _event_rows(conn: sqlite3.Connection) -> Dict[str, int]:
    if "event_metadata" not in _tables(conn):
        return {}
    return {str(e): int(r) for r, e in conn.execute("SELECT rowid, event_id FROM event_metadata")}


def _attach_critical(layers: dict, critical: Sequence[dict], rows: Dict[str, int]) -> Dict[str, int]:
    """Write critical marks into the shipped L2/L1/raw records as heading lines.

    A mark belongs to a record when its source event row is inside the record's
    row range. Raw records already carry their own >>> lines, so only automatic
    marks are added there. Newest records are filled first, each layer is capped,
    and what is left out is counted. The record body in the pack is not changed;
    the lines are rendered after it.
    """
    placed = []
    for rec in critical:
        row = rows.get(str(rec.get("event_id") or ""))
        if row is not None:
            placed.append((row, rec))
    leftover: Dict[str, int] = {}
    for name in ("l2", "l1", "raw"):
        shown, seen = set(), set()
        for rec in sorted(layers[name]["included"], key=lambda r: r["row_hi"], reverse=True):
            hits = [c for row, c in placed if rec["row_lo"] <= row <= rec["row_hi"]
                    and (name != "raw" or c.get("auto"))]
            seen.update(c["id"] for c in hits)
            hits = [c for c in hits if c["id"] not in shown]
            hits.sort(key=lambda c: (bool(c.get("auto")), -int(c.get("hits") or 0), str(c.get("id"))))
            room = max(0, min(CRITICAL_PER_RECORD, CRITICAL_PER_LAYER - len(shown)))
            take = hits[:room]
            shown.update(c["id"] for c in take)
            rec["critical_lines"] = ["CRITICAL: %s [ev:%s]" % (c["title"], _short_ev(c["event_id"])) for c in take]
        leftover[name] = len(seen - shown)
    return leftover


def _profile(conn: sqlite3.Connection) -> List[dict]:
    if "profile_rows" not in _tables(conn):
        return []
    out = []
    for rid, kind, text, scope, status, created in conn.execute(
        "SELECT id, kind, text, scope, status, created_at FROM profile_rows"
    ):
        body, changed = mask(f"{kind} [{status}] scope={scope}\n{text or ''}")
        out.append({"id": str(rid), "layer": "profile", "status": status or "", "body": body,
                    "secrets_masked": changed, "tokens_estimate": est_tokens(body), "time": created or ""})
    out.sort(key=lambda r: r["id"])
    return out


def _constitution(conn: Optional[sqlite3.Connection], owners: Sequence[str]) -> Tuple[List[dict], str]:
    if conn is None or "cubes_new" not in _tables(conn):
        return [], "absent"
    authors = ["system"] + [o.strip().lower() for o in owners if o.strip()]
    marks = ",".join("?" * len(authors))
    q = ("SELECT cube_id, essence, rules_markdown, created_by, status FROM cubes_new "
         "WHERE cube_id LIKE 'cube_const_%' AND lower(created_by) IN (" + marks + ") "
         "AND coalesce(status,'') NOT IN ('deprecated','archived','quarantine','source')")
    latest = {}
    for eid, essence, raw, _by, _st in conn.execute(q, authors):
        num = eid.replace("cube_const_", "").split("_")[0]
        m = re.search(r"_v(\d+)$", eid)
        ver = int(m.group(1)) if m else -1
        if num not in latest or ver > latest[num][0]:
            latest[num] = (ver, eid, essence or "", raw or "")
    out = []
    for num in sorted(latest):
        _ver, eid, essence, raw = latest[num]
        body, changed = mask(raw)
        out.append({"id": eid, "layer": "constitution", "cube": "CUBE " + num.zfill(2),
                    "essence": essence, "body": body, "secrets_masked": changed,
                    "tokens_estimate": est_tokens(body)})
    return out, "present" if out else "absent"


def _registry(conn: Optional[sqlite3.Connection]) -> Tuple[List[dict], str]:
    """Access rows without the secret column. Never selects api_key."""
    if conn is None or "user_api_keys" not in _tables(conn):
        return [], "absent"
    cols = {r[1] for r in conn.execute("PRAGMA table_info(user_api_keys)")}
    if "api_key" in cols and "key_prefix" not in cols and "label" not in cols:
        return [], "absent"
    safe = [c for c in ("user_id", "is_active", "created_at", "expires_at", "key_prefix", "label", "chain_id", "kind", "name") if c in cols]
    if not safe:
        return [], "absent"
    out = []
    fetched = list(conn.execute("SELECT " + ", ".join(safe) + " FROM user_api_keys"))
    fetched.sort(key=lambda row: tuple("" if v is None else str(v) for v in row))
    for i, row in enumerate(fetched):
        rec = dict(zip(safe, row))
        prefix = str(rec.get("key_prefix") or "")
        if re.fullmatch(r"sk_[A-Za-z0-9]{16,}", prefix):
            rec["key_prefix"] = prefix[:6] + "…[masked]"
        body, changed = mask("\n".join(f"{k}: {rec.get(k) if rec.get(k) is not None else ''}" for k in safe))
        out.append({"id": f"key:{i}", "layer": "access", "body": body, "secrets_masked": changed,
                    "tokens_estimate": est_tokens(body)})
    return out, "present" if out else "absent"


def _registry_counts(conn: Optional[sqlite3.Connection], user_id: str) -> Tuple[int, int]:
    """Keys and active keys of this account only. Another account is never counted."""
    if conn is None or "user_api_keys" not in _tables(conn):
        return 0, 0
    cols = {r[1] for r in conn.execute("PRAGMA table_info(user_api_keys)")}
    if "user_id" not in cols:
        return 0, 0
    active = "sum(coalesce(is_active,0))" if "is_active" in cols else "0"
    total, act = conn.execute("SELECT count(*), %s FROM user_api_keys WHERE lower(user_id)=lower(?)" % active, (user_id,)).fetchone()
    return int(total or 0), int(act or 0)


def build_pack(user_conn: sqlite3.Connection, shared_conn: Optional[sqlite3.Connection] = None,
               owners: Optional[Sequence[str]] = None) -> dict:
    owners = list(owners or ["denizchavdarov@gmail.com"])
    raw_all = _raw_records(user_conn)
    raw = _take(raw_all, BUDGET)
    raw_before = min((r["rowid"] for r in raw["included"]), default=None)
    l1_all, l1_overlap = _l1_records(user_conn, raw_before)
    l1 = _take(l1_all, BUDGET)
    if l1["included"]:
        l2_before = min(r["row_lo"] for r in l1["included"])
    else:
        l2_before = raw_before
    l2_all, l2_notes = _l2_records(user_conn, l2_before)
    l2 = _take(l2_all, BUDGET)
    critical = _critical(user_conn)
    board = _board(user_conn)
    open_lines, closed_items = _open_items(board)
    tasks = [dict(r, layer="tasks") for r in board if r.get("kind") == "task"]
    profile = _profile(user_conn)
    constitution, const_status = _constitution(shared_conn, owners)
    registry, reg_status = _registry(shared_conn)
    layers = {"raw": raw, "l1": l1, "l2": l2}
    critical_left = _attach_critical(layers, critical, _event_rows(user_conn))
    reg_total, reg_active = _registry_counts(shared_conn, owners[0])
    spans = {
        "raw": _span(raw["included"], "rowid", "rowid"),
        "l1": _span(l1["included"], "row_lo", "row_hi"),
        "l2": _span(l2["included"], "row_lo", "row_hi"),
    }
    overlap_ok, overlap_reason = _ranges_ok(spans)
    return {
        "token_count": TOKEN_METHOD,
        "budget_each": BUDGET,
        "layers": layers,
        "spans": spans,
        "overlap_ok": overlap_ok,
        "overlap_reason": overlap_reason,
        "gaps": {
            "l1_not_older_than_raw": l1_overlap,
            "l2_not_older_than_l1": l2_notes["overlap_ids"],
            "legacy_l2_map": l2_notes["legacy_map"],
            "raw_rows_not_reached": max(0, len(raw_all) - len(raw["included"]) - (1 if raw["excluded_next"] else 0)),
        },
        "critical": critical,
        "critical_not_listed": critical_left,
        "open_items": open_lines,
        "open_items_closed": closed_items,
        "constitution": constitution,
        "constitution_status": const_status,
        "board": board,
        "profile": profile,
        "tasks": tasks,
        "access_registry": registry,
        "access_registry_status": reg_status,
        "access_registry_keys": reg_total,
        "access_registry_active": reg_active,
    }


def _ranges_ok(spans: dict) -> Tuple[bool, str]:
    raw, l1, l2 = spans["raw"], spans["l1"], spans["l2"]
    if not raw["empty"] and not l1["empty"] and l1["rowid_max"] >= raw["rowid_min"]:
        return False, "l1 overlaps raw"
    if not raw["empty"] and l1["empty"] and not l2["empty"] and l2["rowid_max"] >= raw["rowid_min"]:
        return False, "l2 overlaps raw"
    if not l1["empty"] and not l2["empty"] and l2["rowid_max"] >= l1["rowid_min"]:
        return False, "l2 overlaps l1"
    return True, "rowid ranges do not overlap; empty layers have no range"


def _frame(rec: dict) -> str:
    body = rec.get("body") or ""
    raw = body.encode("utf-8")
    ident = str(rec.get("id") or "").replace("\n", " ")
    return f"<<<RECORD layer={rec['layer']} id={ident} bytes={len(raw)}>>>\n" + body + "\n<<<END>>>\n"


def _oldest(records, key):
    """Stable display order. A new record appends; it does not reshuffle the prefix."""
    return sorted(records or [], key=lambda r: (r.get(key) or 0, str(r.get("id") or "")))


def _by_id(records):
    return sorted(records or [], key=lambda r: str(r.get("id") or ""))


def render_document(pack: dict) -> str:
    """One document, stable prefix first.

    constitution, profile, L2, L1, raw, then the open items, the access counter
    and pack_status. Critical marks are not a section: they are heading lines
    inside the L2/L1/raw records whose rows contain their source events.
    Clocks, token totals and overlap notes stay in pack_status at the end.
    """
    parts = [
        "SKV memory pack 8/8/8\n",
        "token_method: memory_v2.est_tokens\n",
        "token_exact: false\n",
        "formula: ceil(ascii_chars/4 + non_ascii_chars/2.5)\n",
        "budget_each: %s\n\n" % BUDGET,
    ]

    def section(title):
        parts.append("## %s\n\n" % title)

    section("constitution")
    constitution = sorted(
        pack.get("constitution") or [],
        key=lambda r: (str(r.get("cube") or ""), str(r.get("id") or "")),
    )
    if not constitution:
        parts.append("CONSTITUTION ABSENT\n\n")
    for rec in constitution:
        parts.append("=== %s (%s) ===\n" % (rec.get("cube") or "CUBE", rec.get("id") or ""))
        essence = str(rec.get("essence") or "").replace("\n", " ").strip()
        if essence:
            parts.append(essence + "\n")
        parts.append(_frame(rec))
    section("profile")
    for rec in _by_id(pack.get("profile") or []):
        parts.append(_frame(rec))
    for name, key in (("l2", "row_lo"), ("l1", "row_lo"), ("raw", "rowid")):
        section(name)
        for rec in _oldest(pack["layers"][name]["included"], key):
            lines = rec.get("critical_lines") or []
            parts.append(_frame(dict(rec, body=rec["body"] + "\n" + "\n".join(lines)) if lines else rec))
        left = (pack.get("critical_not_listed") or {}).get(name) or 0
        if left:
            parts.append("CRITICAL: +%d more marks in these rows, not listed (POST /api/v7/memory with budget_critical)\n\n" % left)
    section("open_items")
    open_lines = pack.get("open_items") or []
    body = "\n".join(open_lines) if open_lines else "none"
    body += "\nclosed: %d done or parked, not listed. Full cards: board_list tool or GET /api/v7/board.\n" % int(pack.get("open_items_closed") or 0)
    parts.append(_frame({"layer": "open_items", "id": "open_items", "body": body}))
    section("access_registry")
    if pack.get("access_registry_status") == "absent":
        parts.append("access_registry: absent. No access registry without a secret column was found.\n\n")
    else:
        parts.append("access_registry: %d keys, %d active. Full list: https://skv.network/profile (named keys); service accesses of this line are in service_accesses.\n\n"
                     % (int(pack.get("access_registry_keys") or 0), int(pack.get("access_registry_active") or 0)))
    extra = pack.get("service_accesses") or []
    if extra:
        parts.append("## service_accesses\n")
        parts.append("count: %d\n" % len(extra))
        parts.append("note: one row per service access on this memory line; a listing is not permission to act\n\n")
        for rec in extra:
            parts.append(_frame(rec))
    parts.append("## pack_status\n")
    parts.append("overlap_ok: %s\n" % str(pack["overlap_ok"]).lower())
    parts.append("overlap_reason: %s\n" % pack["overlap_reason"])
    parts.append("access_registry: %s\n" % pack["access_registry_status"])
    parts.append("constitution: %s\n" % pack["constitution_status"])
    parts.append("legacy_l2_map: %s\n" % pack["gaps"]["legacy_l2_map"])
    for name in ("l2", "l1", "raw"):
        layer = pack["layers"][name]
        span = pack["spans"][name]
        ex = layer["excluded_next"]
        parts.append("## %s_status\n" % name)
        parts.append("tokens_estimate: %s\n" % layer["tokens_estimate"])
        parts.append("underfill: %s\n" % layer["underfill"])
        parts.append("stopped_because: %s\n" % layer["stopped_because"])
        parts.append("excluded_next: %s\n" % (
            ex["id"] + " tokens_estimate=" + str(ex["tokens_estimate"]) if ex else "none"
        ))
        parts.append("rowid_min: %s\n" % span["rowid_min"])
        parts.append("rowid_max: %s\n" % span["rowid_max"])
        parts.append("time_min: %s\n" % span["time_min"])
        parts.append("time_max: %s\n" % span["time_max"])
    return "".join(parts)


def parse_records(document: str) -> List[dict]:
    data = document.encode("utf-8")
    out = []
    pos = 0
    marker = b"<<<RECORD "
    while True:
        i = data.find(marker, pos)
        if i < 0:
            break
        nl = data.find(b"\n", i)
        head = data[i:nl].decode("utf-8")
        if head.endswith(">>>"):
            head = head[:-3]
        meta = dict(part.split("=", 1) for part in head[len("<<<RECORD "):].split(" ") if "=" in part)
        n = int(meta["bytes"])
        start = nl + 1
        body = data[start:start + n].decode("utf-8")
        out.append({"layer": meta["layer"], "id": meta["id"], "body": body})
        pos = start + n
    return out


def split_bytes(data: bytes, size: int) -> List[bytes]:
    if size < 4:
        raise ValueError("part size must be at least 4 bytes")
    parts, i, n = [], 0, len(data)
    while i < n:
        j = min(n, i + size)
        if j < n:
            while j > i and (data[j] & 0xC0) == 0x80:
                j -= 1
            if j == i:
                j = min(n, i + size)
        parts.append(data[i:j])
        i = j
    return parts or [b""]


def _read(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _layer_public(name: str, layer: dict, span: dict) -> dict:
    return {
        "tokens_estimate": layer["tokens_estimate"],
        "budget": BUDGET,
        "exact": False,
        "count": len(layer["included"]),
        "underfill": layer["underfill"],
        "stopped_because": layer["stopped_because"],
        "excluded_next": layer["excluded_next"],
        "rowid_min": span["rowid_min"],
        "rowid_max": span["rowid_max"],
        "time_min": span["time_min"],
        "time_max": span["time_max"],
        "ids": [r["id"] for r in layer["included"]],
        "secrets_masked_ids": [r["id"] for r in layer["included"] if r.get("secrets_masked")],
    }


def write_snapshot(pack: dict, out_dir: str, part_bytes: int = 32768) -> str:
    if not pack["overlap_ok"]:
        raise RuntimeError("refusing to write an overlapping snapshot: " + pack["overlap_reason"])
    document = render_document(pack)
    leaks = leak_names(document)
    if leaks:
        raise RuntimeError("refusing to write snapshot; secret patterns remain: " + ",".join(leaks))
    raw = document.encode("utf-8")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    short = sha256(raw)[:12]
    dest = os.path.join(out_dir, f"pack888_{stamp}_{short}")
    os.makedirs(dest, exist_ok=False)
    doc_path = os.path.join(dest, "snapshot.txt")
    gz_path = os.path.join(dest, "snapshot.txt.gz")
    with open(doc_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(document)
    with open(doc_path, "rb") as f:
        disk = f.read()
    if disk != raw:
        raise RuntimeError("snapshot bytes changed while writing")
    with gzip.GzipFile(gz_path, "wb", mtime=0) as gz:
        gz.write(raw)
    with gzip.open(gz_path, "rb") as gz:
        if gz.read() != raw:
            raise RuntimeError("gzip did not round-trip")
    parts = split_bytes(raw, part_bytes)
    part_dir = os.path.join(dest, "parts")
    os.makedirs(part_dir)
    part_meta = []
    for n, chunk in enumerate(parts, 1):
        name = f"part-{n:04d}.bin"
        with open(os.path.join(part_dir, name), "wb") as f:
            f.write(chunk)
        part_meta.append({"name": name, "bytes": len(chunk), "sha256": sha256(chunk)})
    if b"".join(parts) != raw:
        raise RuntimeError("parts do not rebuild the snapshot")
    manifest = {
        "kind": "skv_memory_pack_888",
        "created_utc": stamp,
        "token_count": TOKEN_METHOD,
        "budget_each": BUDGET,
        "document": {"path": "snapshot.txt", "bytes": len(raw), "sha256": sha256(raw)},
        "gzip": {"path": "snapshot.txt.gz", "sha256": sha256(_read(gz_path)),
                 "note": "transport copy only; content is the full document"},
        "parts": {"part_bytes_max": part_bytes, "files": part_meta,
                  "concat_sha256": sha256(b"".join(parts))},
        "layers": {name: _layer_public(name, pack["layers"][name], pack["spans"][name]) for name in ("raw", "l1", "l2")},
        "overlap_ok": True,
        "overlap_reason": pack["overlap_reason"],
        "gaps": {
            "l1_overlap_or_unplaced_count": len(pack["gaps"]["l1_not_older_than_raw"]),
            "l1_overlap_or_unplaced_ids": pack["gaps"]["l1_not_older_than_raw"],
            "l2_overlap_or_unplaced_count": len(pack["gaps"]["l2_not_older_than_l1"]),
            "l2_overlap_or_unplaced_ids": pack["gaps"]["l2_not_older_than_l1"],
            "legacy_l2_map": pack["gaps"]["legacy_l2_map"],
            "raw_rows_after_window": pack["gaps"]["raw_rows_not_reached"],
        },
        "sections": {
            "critical": len(pack["critical"]),
            "constitution": len(pack["constitution"]),
            "constitution_status": pack["constitution_status"],
            "board": len(pack["board"]),
            "profile": len(pack["profile"]),
            "tasks": len(pack["tasks"]),
            "access_registry": pack["access_registry_status"],
            "access_registry_rows": len(pack["access_registry"]),
            "access_registry_keys": pack.get("access_registry_keys", 0),
            "open_items": len(pack.get("open_items") or []),
            "critical_not_listed": pack.get("critical_not_listed") or {},
        },
        "checks": {
            "whole_records": True,
            "ranges_disjoint": True,
            "secret_scan": "pass",
            "gzip_roundtrip": True,
            "parts_roundtrip": True,
        },
    }
    with open(os.path.join(dest, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")
    verify_snapshot(dest)
    return dest


def verify_snapshot(dest: str) -> dict:
    with open(os.path.join(dest, "manifest.json"), encoding="utf-8") as f:
        man = json.load(f)
    doc = _read(os.path.join(dest, "snapshot.txt"))
    if sha256(doc) != man["document"]["sha256"]:
        raise RuntimeError("document sha256 mismatch")
    gz_bytes = _read(os.path.join(dest, "snapshot.txt.gz"))
    if sha256(gz_bytes) != man["gzip"]["sha256"]:
        raise RuntimeError("gzip sha256 mismatch")
    if gzip.decompress(gz_bytes) != doc:
        raise RuntimeError("gzip payload mismatch")
    joined = b""
    for part in man["parts"]["files"]:
        chunk = _read(os.path.join(dest, "parts", part["name"]))
        if sha256(chunk) != part["sha256"] or len(chunk) != part["bytes"]:
            raise RuntimeError("part mismatch: " + part["name"])
        joined += chunk
    if joined != doc or sha256(joined) != man["parts"]["concat_sha256"]:
        raise RuntimeError("parts do not rebuild the document")
    leaks = leak_names(doc.decode("utf-8"))
    if leaks:
        raise RuntimeError("secret patterns in snapshot: " + ",".join(leaks))
    if not man.get("overlap_ok"):
        raise RuntimeError("manifest says ranges overlap")
    return man


def owner_list(user_id: str) -> List[str]:
    env = [u.strip() for u in os.environ.get("SKV_SHELL_OWNERS", "denizchavdarov@gmail.com").split(",") if u.strip()]
    out: List[str] = []
    for u in [user_id] + env:
        if u and u not in out:
            out.append(u)
    return out


def load_pack(user_id: str, user_db: str = "", shared_db: str = "") -> dict:
    udb = user_db or account_db(user_id)
    sdb = shared_db or SHARED_DB
    if not user_id or not os.path.exists(udb):
        raise RuntimeError("user database not found")
    user = _ro(udb)
    shared = _ro(sdb) if os.path.exists(sdb) else None
    try:
        pack = build_pack(user, shared, owners=owner_list(user_id))
    finally:
        user.close()
        if shared:
            shared.close()
    if not pack["overlap_ok"]:
        raise RuntimeError("refusing overlapping pack: " + pack["overlap_reason"])
    return pack


def load_document(user_id: str, user_db: str = "", shared_db: str = "") -> str:
    document = render_document(load_pack(user_id, user_db, shared_db))
    leaks = leak_names(document)
    if leaks:
        raise RuntimeError("refusing pack; secret patterns remain: " + ",".join(leaks))
    return document


# One step_zero page stays under the uncompressed HTTPS stall (~15.7 KB).
# The tool JSON cap is ~12 KB so the JSON-RPC wrapper still fits under ~15 KB.
# REST may join these slices and cut again on its own limits.
STEP_ZERO_PAGE_TEXT = 11000
STEP_ZERO_MAX_JSON = 12000
_PACK_MARK = "=== PACK888 %03d/%03d concatenate the text after this line, in order ===\n"
_PACK_MARK_RE = re.compile(r"^=== PACK888 (\d{3})/(\d{3}) concatenate the text after this line, in order ===\n")


def separate_pack_marks(text: str) -> str:
    """Keep each PACK888 header on its own line. A joined page must not glue it to the previous character."""
    return re.sub(r"(?<=\S)(=== PACK888 )", "\n\\1", text or "")


def _page_mark(i: int, n: int, body: str) -> str:
    return (_PACK_MARK % (i, n)) + body


def step_zero_envelope_len(text: str) -> int:
    obj = {
        "page": 99,
        "pages": 99,
        "done": False,
        "next_page": 100,
        "next": (
            "call step_zero(page=100) now. Pages 2..99 are the memory pack 8/8/8: "
            "concatenate the text under each PACK888 line, in order. A record may continue "
            "on the next page. Read every page until done=true."
        ),
        "text": text,
    }
    return len(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))


def _page_fits(body: str, max_json: int, max_text: int) -> bool:
    page = _page_mark(0, 0, body)
    return len(page) <= max_text and step_zero_envelope_len(page) <= max_json


def split_document(text: str, max_json: int = STEP_ZERO_MAX_JSON, max_text: int = STEP_ZERO_PAGE_TEXT) -> List[str]:
    """Split one document into step_zero pages that join back to the same text.

    A full page stays under STEP_ZERO_PAGE_TEXT. A page ends on a record boundary when
    that still fits. A record longer than one response is split, and the next
    page continues it. Nothing is dropped.
    """
    if not _page_fits("x", max_json, max_text):
        raise RuntimeError("step_zero page limit is smaller than the page marker")
    bodies: List[str] = []
    i, n = 0, len(text)
    if n == 0:
        bodies = [""]
    end_mark = "<<<END>>>\n"
    while i < n:
        lo, hi, best = 1, n - i, 0
        while lo <= hi:
            mid = (lo + hi) // 2
            if _page_fits(text[i:i + mid], max_json, max_text):
                best = mid
                lo = mid + 1
            else:
                hi = mid - 1
        if best < 1:
            raise RuntimeError("a single character does not fit in a step_zero page")
        snap = text.rfind(end_mark, i, i + best)
        snap_len = 0 if snap < i else snap + len(end_mark) - i
        if snap_len >= max(200, best // 5):
            best = snap_len
        bodies.append(text[i:i + best])
        i += best
    total = len(bodies)
    if total > 999:
        raise RuntimeError("pack needs more than 999 step_zero pages")
    pages = [_page_mark(k, total, b) for k, b in enumerate(bodies, 1)]
    for p in pages:
        if len(p) > max_text or step_zero_envelope_len(p) > max_json:
            raise RuntimeError("pack page exceeds step_zero response limit")
    if join_pack_pages(pages) != text:
        raise RuntimeError("pack pages do not rebuild the document")
    return pages


def join_pack_pages(pages: Sequence[str]) -> str:
    parts = []
    for p in pages:
        m = _PACK_MARK_RE.match(p)
        if not m:
            raise ValueError("not a pack page")
        parts.append(p[m.end():])
    return "".join(parts)


def pack_span(pages: Sequence[str]) -> Optional[Tuple[int, int]]:
    idxs = [i + 1 for i, p in enumerate(pages) if p.startswith("=== PACK888 ")]
    if not idxs:
        return None
    return idxs[0], idxs[-1]


def assemble_step_zero(intro_pages: Sequence[str], pack_pages: Sequence[str], constitution_pages: Sequence[str]) -> List[str]:
    return list(intro_pages) + list(pack_pages) + list(constitution_pages)


def step_zero_next(page: int, pages: Sequence[str]) -> str:
    n = len(pages)
    span = pack_span(pages)
    if page >= n:
        return "step zero complete: answer the user using turn(user_message, draft)"
    if span and page < span[1]:
        return (
            "call step_zero(page=%d) now. Pages %d..%d are the memory pack 8/8/8: "
            "concatenate the text under each PACK888 line, in order. A record may continue "
            "on the next page. Read every page until done=true."
        ) % (page + 1, span[0], span[1])
    return (
        "call step_zero(page=%d) now. Remaining pages are the constitution "
        "(CUBE 00-04 + CUBE 05-MCP). Read every page until done=true."
    ) % (page + 1)


def export_user(user_id: str, out_dir: str, user_db: str = "", shared_db: str = "", part_bytes: int = 32768) -> str:
    return write_snapshot(load_pack(user_id, user_db, shared_db), out_dir, part_bytes=part_bytes)


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Write one immutable SKV 8/8/8 memory snapshot")
    sub = p.add_subparsers(dest="cmd", required=True)
    ex = sub.add_parser("export")
    ex.add_argument("--user", required=True)
    ex.add_argument("--out", required=True)
    ex.add_argument("--user-db", default="")
    ex.add_argument("--shared-db", default="")
    ex.add_argument("--part-bytes", type=int, default=32768)
    vf = sub.add_parser("verify")
    vf.add_argument("--dir", required=True)
    jn = sub.add_parser("join")
    jn.add_argument("--dir", required=True)
    jn.add_argument("--out", required=True)
    args = p.parse_args(argv)
    if args.cmd == "export":
        dest = export_user(args.user, args.out, args.user_db, args.shared_db, args.part_bytes)
        man = json.load(open(os.path.join(dest, "manifest.json"), encoding="utf-8"))
        summary = {
            "dir": dest,
            "layers": {k: {"tokens_estimate": v["tokens_estimate"], "count": v["count"],
                           "underfill": v["underfill"], "stopped_because": v["stopped_because"],
                           "rowid_min": v["rowid_min"], "rowid_max": v["rowid_max"]}
                       for k, v in man["layers"].items()},
            "sections": man["sections"],
            "checks": man["checks"],
            "sha256": man["document"]["sha256"],
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "verify":
        man = verify_snapshot(args.dir)
        print(json.dumps({"ok": True, "sha256": man["document"]["sha256"]}, ensure_ascii=False))
        return 0
    dest = args.dir
    man = json.load(open(os.path.join(dest, "manifest.json"), encoding="utf-8"))
    joined = b"".join(_read(os.path.join(dest, "parts", part["name"])) for part in man["parts"]["files"])
    if sha256(joined) != man["document"]["sha256"]:
        raise SystemExit("join mismatch")
    with open(args.out, "wb") as f:
        f.write(joined)
    print(args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
