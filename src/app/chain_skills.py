"""Per-chain attached skill cubes (install / uninstall).

Ask-then-install: never attach silently. Caller must pass user_confirmed=True
(user said yes to the offer) OR user_said_install=True (user already said
'install/attach this cube').

Storage: user metadata DB table chain_skills(chain_id, cube_id, ...).
Private cubes: owner chain only (must live in that user's experience_cubes).
Shared cubes: after existing publish Guard; install still needs explicit yes.
"""
from __future__ import annotations

import json
import re
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from app import cubes_v2 as _cv2
from app.memory_v2 import db_path as _user_db

SHARED_DB = "/data/skv/metadata_store/shared_master.db"
DEFAULT_CHAIN = "session"
MAX_ATTACHED = 24
# Connecting an agent to SKV = consent for these. Auto-attach on Step 0 / bootstrap.
# All other skill cubes: offer → ask → install only on yes (or explicit install/attach).
DEFAULT_AUTO_ATTACH = (
    "cube_skill_const_second_look",
    "cube_skill_const_memory",
    "cube_skill_const_close",
    "cube_skill_const_cube_install",
    "cube_skill_const_pin_turn",  # CUBE 05 v14 pinned turn item
    "cube_688c0ebbb3be",  # meta: create-cubes author skill
)
SKILL_MD_CAP = 6000
HOOKS_CAP = 2000


def ensure(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS chain_skills (
            chain_id TEXT NOT NULL,
            cube_id TEXT NOT NULL,
            source TEXT,
            topic TEXT,
            attached_at TEXT,
            attached_by TEXT,
            PRIMARY KEY (chain_id, cube_id)
        )"""
    )


def _conn(uid: str, *, rw: bool = True) -> sqlite3.Connection:
    path = _user_db(uid)
    if rw:
        c = sqlite3.connect(path, timeout=30)
        ensure(c)
        try:
            _cv2.migrate_private_schema(c)
        except Exception:
            pass
    else:
        # Read-only: never CREATE/ALTER (breaks resolve before chain_skills exists).
        c = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    return c


def _norm_chain(chain_id: Optional[str]) -> str:
    c = (chain_id or "").strip()
    return c or DEFAULT_CHAIN


_REF_MARK = re.compile(r"^#{1,3}\s*PART 2\b.*$", re.M)


def core_only(skill: str) -> str:
    """Installed skills ship only their CORE; text after a '## PART 2 ...' heading stays in cube_get."""
    m = _REF_MARK.search(skill or "")
    if not m:
        return skill or ""
    return skill[:m.start()].rstrip() + "\n\n[PART 2 REFERENCE not loaded: cube_get(cube_id) when a step says so]\n"


def newest_version(cube_id: str, hops: int = 8) -> str:
    """Follow status=superseded -> links_json.superseded_by to the newest version."""
    cid = cube_id
    try:
        sc = sqlite3.connect(f"file:{SHARED_DB}?mode=ro", uri=True, timeout=10)
        try:
            for _ in range(hops):
                r = sc.execute("SELECT coalesce(status,''), links_json FROM cubes_new WHERE cube_id=?", (cid,)).fetchone()
                if not r or r[0] != "superseded":
                    break
                try:
                    nxt = (json.loads(r[1] or "{}") or {}).get("superseded_by")
                except Exception:
                    nxt = None
                if not nxt:
                    break
                cid = nxt
        finally:
            sc.close()
    except Exception:
        return cube_id
    return cid


def resolve_cube(uid: str, cube_id: str) -> Optional[Dict[str, Any]]:
    """Shared cubes_new first, else caller's private experience_cubes."""
    cid = (cube_id or "").strip()
    if not cid:
        return None
    shared = True
    row = None
    topic = ""
    try:
        sc = sqlite3.connect(f"file:{SHARED_DB}?mode=ro", uri=True, timeout=10)
        try:
            _cv2.ensure(sc)
            row = sc.execute(
                "SELECT cube_id, essence, rules_markdown, status, kind, skill_md, hooks, carrier, "
                "COALESCE(subject_action_object,'') FROM cubes_new WHERE cube_id=?",
                (cid,),
            ).fetchone()
        finally:
            sc.close()
    except Exception:
        row = None
    if row:
        status = (row[3] or "").lower()
        if status in _cv2.HIDDEN_STATUS:
            return None
        topic = row[8] or ""
        pack = {
            "cube_id": row[0],
            "essence": row[1] or "",
            "rules": row[2] or "",
            "status": row[3] or "",
            "kind": row[4] or "moment",
            "skill_md": row[5] or "",
            "hooks_raw": row[6] or "",
            "carrier": _cv2.norm_carrier(row[7] or "", row[5] or "", row[6] or ""),
            "topic": topic,
            "shared": True,
            "source": "shared",
        }
    else:
        if not uid:
            return None
        try:
            pc = _conn(uid, rw=False)
            try:
                prow = pc.execute(
                    "SELECT cube_id, essence, rules_markdown, kind, skill_md, hooks, carrier, topic "
                    "FROM experience_cubes WHERE cube_id=?",
                    (cid,),
                ).fetchone()
            finally:
                pc.close()
        except Exception:
            prow = None
        if not prow:
            return None
        pack = {
            "cube_id": prow[0],
            "essence": prow[1] or "",
            "rules": prow[2] or "",
            "status": "private",
            "kind": prow[3] or "moment",
            "skill_md": prow[4] or "",
            "hooks_raw": prow[5] or "",
            "carrier": _cv2.norm_carrier(prow[6] or "", prow[4] or "", prow[5] or ""),
            "topic": prow[7] or "",
            "shared": False,
            "source": "private",
        }
    hooks = _cv2.parse_hooks(pack.pop("hooks_raw"))
    pack["hooks"] = hooks
    pack["has_skill"] = bool(
        pack["carrier"] == "skill" or pack["skill_md"] or hooks
    )
    return pack


def _clip(s: str, n: int) -> str:
    s = s or ""
    return s if len(s) <= n else s[: n - 1] + "…"


def list_ids(uid: str, chain_id: Optional[str]) -> List[Dict[str, str]]:
    chain = _norm_chain(chain_id)
    # Ensure schema with a short rw open (list itself stays read)
    try:
        _cw = _conn(uid, rw=True)
        _cw.close()
    except Exception:
        pass
    c = _conn(uid, rw=False)
    try:
        rows = c.execute(
            "SELECT cube_id, source, topic, attached_at, attached_by FROM chain_skills "
            "WHERE chain_id=? ORDER BY attached_at",
            (chain,),
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    finally:
        c.close()
    return [
        {
            "cube_id": r[0],
            "source": r[1] or "",
            "topic": r[2] or "",
            "attached_at": r[3] or "",
            "attached_by": r[4] or "",
            "chain_id": chain,
        }
        for r in rows
    ]



def ensure_defaults(uid: str, chain_id: Optional[str], *, attached_by: str = "bootstrap_consent") -> Dict[str, Any]:
    """Auto-attach constitution hooks + meta create-cubes (owner consent on connect).
    Does NOT require user_confirmed — connecting the agent IS the consent for these ids only.
    """
    if not uid:
        return {"ok": False, "error": "API key required", "attached": []}
    chain = _norm_chain(chain_id)
    attached, missing, skipped = [], [], []
    for cid in DEFAULT_AUTO_ATTACH:
        pack = resolve_cube(uid, cid)
        if not pack:
            missing.append(cid)
            continue
        if not pack.get("has_skill") and pack.get("carrier") != "skill":
            skipped.append(cid)
            continue
        # silent for defaults only — bypass ask_first
        c = _conn(uid, rw=True)
        try:
            ensure(c)
            exists = c.execute(
                "SELECT 1 FROM chain_skills WHERE chain_id=? AND cube_id=?",
                (chain, cid),
            ).fetchone()
            if exists:
                skipped.append(cid)
                continue
            n = c.execute("SELECT COUNT(*) FROM chain_skills WHERE chain_id=?", (chain,)).fetchone()[0]
            if int(n) >= MAX_ATTACHED:
                missing.append(cid)
                continue
            c.execute(
                "INSERT INTO chain_skills (chain_id, cube_id, source, topic, attached_at, attached_by) "
                "VALUES (?,?,?,?,datetime('now'),?)",
                (chain, cid, pack["source"], (pack.get("topic") or "")[:200], (attached_by or "bootstrap_consent")[:120]),
            )
            c.commit()
            attached.append(cid)
        finally:
            c.close()
    return {"ok": True, "chain_id": chain, "attached": attached, "already_or_skip": skipped, "missing": missing}


def attached_pack(
    uid: str,
    chain_id: Optional[str],
    *,
    max_cubes: int = 12,
    skill_budget: int = 16000,
) -> List[Dict[str, Any]]:
    """Bootstrap payload: skill_md + hooks for installed cubes (token-capped)."""
    ids = list_ids(uid, chain_id)
    ids.sort(key=lambda m: 0 if (m.get("cube_id") or "").startswith(("cube_skill_const", "cube_const_")) else 1)
    ids = ids[:max_cubes]
    out: List[Dict[str, Any]] = []
    used = 0
    for meta in ids:
        _cid, _was = newest_version(meta["cube_id"]), meta["cube_id"]
        pack = resolve_cube(uid, _cid)
        if pack and _cid != _was:
            pack["upgraded_from"] = _was
        if not pack:
            out.append({
                "cube_id": meta["cube_id"],
                "source": meta["source"],
                "topic": meta["topic"],
                "attached_at": meta["attached_at"],
                "missing": True,
                "hint": "cube not found (deleted or not visible)",
            })
            continue
        skill = core_only(pack.get("skill_md") or "")
        skill = _clip(skill, SKILL_MD_CAP)
        hooks = pack.get("hooks") or []
        hooks_s = _clip(json.dumps(hooks, ensure_ascii=False), HOOKS_CAP)
        cost = len(skill) + len(hooks_s) + 80
        if used + cost > skill_budget and out:
            out.append({
                "cube_id": pack["cube_id"],
                "topic": pack.get("topic") or meta["topic"],
                "source": pack["source"],
                "carrier": pack["carrier"],
                "attached_at": meta["attached_at"],
                "truncated": True,
                "hint": "budget; cube_get for full skill_md",
            })
            continue
        used += cost
        item = {
            "cube_id": pack["cube_id"],
            "topic": pack.get("topic") or meta["topic"],
            "essence": _clip(pack.get("essence") or "", 400),
            "carrier": pack["carrier"],
            "source": pack["source"],
            "shared": pack["shared"],
            "attached_at": meta["attached_at"],
            "skill_md": skill,
            "hooks": hooks,
            "has_skill": pack["has_skill"],
        }
        if pack.get("upgraded_from"):
            item["upgraded_from"] = pack["upgraded_from"]
        if len(skill) < len(pack.get("skill_md") or ""):
            item["skill_md_full"] = "cube_get(cube_id=%s) for the REFERENCE part" % pack["cube_id"]
        out.append(item)
    return out


def install(
    uid: str,
    chain_id: Optional[str],
    cube_id: str,
    *,
    user_confirmed: bool = False,
    user_said_install: bool = False,
    attached_by: str = "",
) -> Dict[str, Any]:
    """Attach cube to chain. Refuses unless user_confirmed or user_said_install."""
    if not uid:
        return {"ok": False, "error": "API key required"}
    if not (user_confirmed or user_said_install):
        return {
            "ok": False,
            "error": "ask_first",
            "hint": (
                "Offer first ('I have experience cubes for X — attach?'). "
                "Install only after explicit yes (user_confirmed=true) "
                "or when the user already said install/attach this cube "
                "(user_said_install=true). Never silent install."
            ),
        }
    cid = (cube_id or "").strip()
    if not cid:
        return {"ok": False, "error": "cube_id required"}
    pack = resolve_cube(uid, cid)
    if not pack:
        return {"ok": False, "error": "cube_not_found", "cube_id": cid}
    if not pack["has_skill"] and pack["carrier"] != "skill":
        return {
            "ok": False,
            "error": "not_a_skill_cube",
            "hint": "Install targets carrier=skill (or cubes with skill_md/hooks).",
            "cube_id": cid,
            "carrier": pack["carrier"],
        }
    # Private: only the owning user's experience_cubes (already enforced by resolve).
    # Shared: publish Guard already ran; still require explicit yes (above).
    chain = _norm_chain(chain_id)
    c = _conn(uid, rw=True)
    try:
        ensure(c)
        n = c.execute("SELECT COUNT(*) FROM chain_skills WHERE chain_id=?", (chain,)).fetchone()[0]
        exists = c.execute(
            "SELECT 1 FROM chain_skills WHERE chain_id=? AND cube_id=?",
            (chain, cid),
        ).fetchone()
        if exists:
            c.commit()
            return {
                "ok": True,
                "already": True,
                "cube_id": cid,
                "chain_id": chain,
                "source": pack["source"],
                "topic": pack.get("topic") or "",
                "carrier": pack["carrier"],
            }
        if int(n) >= MAX_ATTACHED:
            return {
                "ok": False,
                "error": "limit",
                "hint": f"max {MAX_ATTACHED} skills per chain; uninstall one first",
                "count": int(n),
            }
        c.execute(
            "INSERT INTO chain_skills (chain_id, cube_id, source, topic, attached_at, attached_by) "
            "VALUES (?,?,?,?,datetime('now'),?)",
            (
                chain,
                cid,
                pack["source"],
                (pack.get("topic") or "")[:200],
                (attached_by or uid)[:120],
            ),
        )
        c.commit()
    finally:
        c.close()
    return {
        "ok": True,
        "installed": True,
        "cube_id": cid,
        "chain_id": chain,
        "source": pack["source"],
        "topic": pack.get("topic") or "",
        "carrier": pack["carrier"],
        "has_skill": pack["has_skill"],
        "note": "skill_md+hooks available via bootstrap attached_skills and cube_get",
    }


def uninstall(uid: str, chain_id: Optional[str], cube_id: str) -> Dict[str, Any]:
    if not uid:
        return {"ok": False, "error": "API key required"}
    cid = (cube_id or "").strip()
    if not cid:
        return {"ok": False, "error": "cube_id required"}
    chain = _norm_chain(chain_id)
    c = _conn(uid, rw=True)
    try:
        ensure(c)
        cur = c.execute(
            "DELETE FROM chain_skills WHERE chain_id=? AND cube_id=?",
            (chain, cid),
        )
        n = cur.rowcount
        c.commit()
    finally:
        c.close()
    return {
        "ok": True,
        "uninstalled": bool(n),
        "cube_id": cid,
        "chain_id": chain,
        "removed": int(n or 0),
    }


def chain_from_request(request, authorization: str = None, x_api_key: str = None, key: str = None) -> Tuple[str, Optional[str], Optional[str], Optional[str]]:
    """Return (uid, chain_id, chain_name, key_kind) from bearer / state."""
    from app import api_keys as _ak

    uid = ""
    try:
        uid = (getattr(request.state, "user_id", None) or "") if request is not None else ""
    except Exception:
        uid = ""
    token = ""
    if authorization and str(authorization).lower().startswith("bearer "):
        token = str(authorization)[7:].strip()
    if not token and x_api_key:
        token = str(x_api_key).strip()
    if not token and key:
        token = str(key).strip()
    chain_id = chain_name = key_kind = None
    if token:
        info = _ak.chain_for_token(token)
        if info:
            uid = uid or info[0]
            chain_id, chain_name, key_kind = info[1], info[2], info[3]
    return uid or "", chain_id, chain_name, key_kind


def installed_by_others(cube_id: str, author: str) -> int:
    """How many other accounts have this cube (or an older version of it) installed."""
    import glob, os
    ids, cid = set(), cube_id
    try:
        sc = sqlite3.connect(f"file:{SHARED_DB}?mode=ro", uri=True, timeout=10)
        try:
            for _ in range(10):
                if not cid or cid in ids:
                    break
                ids.add(cid)
                r = sc.execute("SELECT parent_id FROM cubes_new WHERE cube_id=?", (cid,)).fetchone()
                cid = r[0] if r else None
        finally:
            sc.close()
    except Exception:
        ids = {cube_id}
    try:
        mine = os.path.realpath(_user_db(author)) if author else ""
    except Exception:
        mine = ""
    n = 0
    q = "SELECT 1 FROM chain_skills WHERE cube_id IN (%s) LIMIT 1" % ",".join("?" * len(ids))
    for path in glob.glob(os.path.join(os.path.dirname(SHARED_DB), "*.db")):
        if os.path.basename(path) == os.path.basename(SHARED_DB) or os.path.realpath(path) == mine:
            continue
        try:
            c = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
            try:
                if c.execute(q, tuple(ids)).fetchone():
                    n += 1
            finally:
                c.close()
        except Exception:
            pass
    return n
