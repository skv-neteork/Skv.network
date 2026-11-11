"""Account purge: remove everything SKV keeps for one user (used by /profile/delete).

Private data is deleted. Shared contributions other people rely on (community cubes, cube links, help answers,
shared events) stay, but the author becomes "deleted_user" and votes are re-attributed to an anonymous id.
Exception: jp_audit rows in projects OWNED BY SOMEONE ELSE stay as they are (the audit is hash-chained and belongs
to that project's owner); audit rows of projects the user owned are deleted with the project."""
import glob
import hashlib
import json
import os
import re
import shutil
import sqlite3

BASE = "/data/skv/metadata_store"
SHARED_DB = os.path.join(BASE, "shared_master.db")
HNSW_DIRS = ("/data/skv/hnsw", "/data/skv/hnsw_mml12")
ANON = "deleted_user"

# tables whose rows are private to the user: (table, column)
PRIVATE = [
    ("vault_secrets", "user_id"), ("vault_log", "user_id"), ("vault_reveals", "user_id"),
    ("agent_duty", "user_id"), ("cube_outcomes", "user_id"), ("cube_impressions", "user_id"),
    ("cube_duty_state", "user_id"), ("cube_suggest_seen", "user_id"), ("cube_consent", "user_id"),
    ("cube_consent_log", "user_id"), ("cube_fixes", "user_id"), ("event_lines", "user_id"),
    ("summary_lines", "user_id"), ("profile_flags", "user_id"), ("agent_inbox", "user_id"),
    ("agent_reputation", "user_id"), ("solution_confirms", "user_id"), ("feedback_reports", "user_id"),
    ("sys_grants", "owner"), ("sys_audit", "user_id"), ("court_judges", "user_id"),
    ("jp_members", "user_id"), ("jp_events", "user_id"), ("project_members", "user_id"),
]
# shared contributions: keep the row, drop the author
ANONYMIZE = [
    ("cubes_new", "created_by"), ("cubes_archive", "created_by"), ("cube_links", "created_by"),
    ("cube_tasks", "created_by"), ("help_requests", "created_by"), ("help_answers", "author"),
    ("event_metadata", "created_by"), ("project_nodes", "created_by"),
]
# side DBs keyed by user (or by sha256(key)[:16] for key-only clients)
SIDE = [("rest_turn.db", "st"), ("compact_state_rest.db", "cst"), ("compact_state_rest.db", "sl_q"),
        ("compact_state_mcp.db", "cst"), ("compact_state_mcp.db", "sl_q"), ("seal_counter.db", "ctr"),
        ("cube_harvest.db", "h")]


def name_variants(user_id, protected=()):
    """File names to remove for this account. `protected` = primary storage names of OTHER registered accounts:
    never returned (2026-11-11: purging "bench-locomo" removed the db of "benchlocomo" through the hyphen-less variant)."""
    from app.account_ids import account_name, legacy_names
    out = {account_name(user_id)} | legacy_names(user_id)
    bad = {"shared_master", "rest_turn", "seal_counter", "cube_harvest", "compact_state_rest", "compact_state_mcp",
           "cube_link", "admin", "demo", "anonymous", "archive", "chrono_buffer"}
    prot = set(protected or ())
    return sorted(v for v in out if v and v not in (".", "..") and "/" not in v and len(v) >= 6 and v not in bad and v not in prot)


def _tables(c):
    return {r[0] for r in c.execute("select name from sqlite_master where type='table'")}


def _anon_votes(c, table, uid, anon_id):
    n = 0
    if "votes_json" not in {r[1] for r in c.execute(f"pragma table_info('{table}')")}:
        return 0
    pk = "cube_id" if table in ("cubes_new", "cubes_archive") else "rowid"
    for rid, vj in c.execute(f"select {pk}, votes_json from {table} where votes_json like ?", ("%" + uid + "%",)).fetchall():
        try:
            votes = json.loads(vj or "[]")
        except Exception:
            continue
        changed = False
        for v in votes if isinstance(votes, list) else []:
            if isinstance(v, dict) and v.get("user_id") == uid:
                v["user_id"] = anon_id
                changed = True
        if changed:
            c.execute(f"update {table} set votes_json=? where {pk}=?", (json.dumps(votes), rid))
            n += 1
    return n


class NameCollision(ValueError):
    """The account's storage name is shared with another registered account: nothing may be deleted."""


def purge(user_id, key_hashes=(), registered=None):
    """Delete the user's rows and files. key_hashes: sha256(key) hex of the user's keys (from user_api_keys).
    registered: all registered emails (default: read from shared_master.users); used to protect other accounts' files."""
    uid = (user_id or "").strip()
    if "@" not in uid:
        raise ValueError("purge: account ids are emails")
    from app.account_ids import conflicting_accounts, protected_names, registered_emails
    if registered is None:
        _c = sqlite3.connect(SHARED_DB, timeout=30)
        try:
            registered = registered_emails(_c)
        finally:
            _c.close()
    if conflicting_accounts(uid, registered):
        raise NameCollision("storage name is shared with another account: refusing to purge")
    protected = protected_names(uid, registered)
    anon_id = "deleted:" + hashlib.sha256(uid.encode()).hexdigest()[:12]
    users = [uid] + [h[:16] for h in key_hashes if h]
    report = {"rows": {}, "anonymized": {}, "files": 0}
    c = sqlite3.connect(SHARED_DB, timeout=30)
    try:
        t = _tables(c)
        # projects the user owns: drop them whole (members, events, audit, nodes)
        if "jp_projects" in t:
            own = [r[0] for r in c.execute("select id from jp_projects where owner=?", (uid,))]
            for pid in own:
                for tb in ("jp_members", "jp_events", "jp_audit"):
                    if tb in t:
                        c.execute(f"delete from {tb} where project_id=?", (pid,))
            c.execute("delete from jp_projects where owner=?", (uid,))
            report["rows"]["jp_projects"] = len(own)
        if "projects" in t:
            own = [r[0] for r in c.execute("select id from projects where owner=?", (uid,))]
            for pid in own:
                for tb in ("project_members", "project_nodes"):
                    if tb in t:
                        c.execute(f"delete from {tb} where project_id=?", (pid,))
            c.execute("delete from projects where owner=?", (uid,))
            report["rows"]["projects"] = len(own)
        for tb, col in PRIVATE:
            if tb in t:
                n = c.execute(f"delete from {tb} where {col}=?", (uid,)).rowcount
                if n:
                    report["rows"][tb] = n
        for tb, col in ANONYMIZE:
            if tb in t:
                n = c.execute(f"update {tb} set {col}=? where {col}=?", (ANON, uid)).rowcount
                n += _anon_votes(c, tb, uid, anon_id)
                if n:
                    report["anonymized"][tb] = n
        c.commit()
    finally:
        c.close()
    for db, tb in SIDE:
        p = os.path.join(BASE, db)
        if not os.path.exists(p):
            continue
        try:
            s = sqlite3.connect(p, timeout=30)
            if tb in _tables(s):
                q = ",".join("?" * len(users))
                n = s.execute(f"delete from {tb} where user in ({q})", users).rowcount
                if n:
                    report["rows"][db + ":" + tb] = n
            s.commit()
            s.close()
        except Exception as e:
            report.setdefault("errors", []).append(f"{db}:{tb}: {e}")
    # files: every name variant, with and without .db, sidecars, chunk/l1 indexes, staging dirs
    _skipped = sorted(set(name_variants(uid)) - set(name_variants(uid, protected)))
    if _skipped:
        report["skipped_other_account_names"] = len(_skipped)   # names only counted, never listed
    for v in name_variants(uid, protected):
        pats = [os.path.join(BASE, v), os.path.join(BASE, v + ".db"), os.path.join(BASE, v + ".db-wal"),
                os.path.join(BASE, v + ".db-shm"), os.path.join(BASE, v + ".db-journal"),
                os.path.join(BASE, glob.escape(v) + "__*.db")]
        for d in HNSW_DIRS:
            pats += [os.path.join(d, v + ".hnsw"), os.path.join(d, v + "_ids.npy"),
                     os.path.join(d, glob.escape(v) + "__*.hnsw"), os.path.join(d, glob.escape(v) + "__*_ids.npy")]
        pats.append(os.path.join("/data/skv/drive_staging", v))
        for pat in pats:
            for p in (glob.glob(pat) if "*" in pat else [pat]):
                try:
                    if os.path.isdir(p) and not os.path.islink(p):
                        shutil.rmtree(p)
                        report["files"] += 1
                    elif os.path.lexists(p):
                        os.remove(p)
                        report["files"] += 1
                except OSError as e:
                    report.setdefault("errors", []).append(f"{os.path.basename(p)}: {e}")
    return report
