"""File one court version of the live author cube. Does not supersede it.

The new text adds the skill-import path, the first-connection hook, and the
line that hooks are required only on skill cubes. Safe to run twice.
"""
import json
import sqlite3
import sys

sys.path.insert(0, "/root/skv-core/src")
from app import cube_dedup as dd

DB = "/data/skv/metadata_store/shared_master.db"
CANON = "cube_3de96286fc73"
MARK = "b2-import-procedure"
HOOK = {
    "when": "first connection of an agent, or about every 3 days, or after a large task",
    "do": "On the first connection, review this account's verified skills as cube candidates. About every 3 days, or after a large task, review only skills that are new since the last review.",
}
RULES_ADD = """

Hooks are required only for skill cubes. Empty hooks on facts and moments are normal.

Import of a verified skill (path 3, the main path): scrub secrets and personal data, record requirements, write skill_md and hooks, check for a duplicate, then publish or cube_confirm. Do not auto-merge. A conflict of hooks goes to the court.
"""
SKILL_ADD = """

## Import a verified skill (path 3)
1. Scrub secrets, mail, hosts, absolute paths, repository names, chain ids and event citations.
2. Record requirements (tool, package, os, permission, skill).
3. Write skill_md and hooks. Hooks are required only for skill cubes.
4. Check for a duplicate. An exact or very close copy is not published; confirm the canonical cube or propose a version.
5. Publish only after the author accepts the scrubbed text. Conflicts go to the court, not to an automatic merge.
"""


def main():
    conn = sqlite3.connect(DB, timeout=30)
    try:
        have = conn.execute(
            "SELECT cube_id FROM cubes_new WHERE parent_id=? AND coalesce(links_json,'') LIKE ?",
            (CANON, "%" + MARK + "%")).fetchone()
        if have:
            print(json.dumps({"ok": True, "skipped": True, "cube_id": have[0]}))
            return
        row = conn.execute(
            "SELECT coalesce(rules_markdown,''), coalesce(skill_md,''), coalesce(hooks,''), coalesce(subject_action_object,''), coalesce(essence,''), coalesce(kind,''), coalesce(carrier,''), coalesce(created_by,'') FROM cubes_new WHERE cube_id=?",
            (CANON,)).fetchone()
        if not row:
            print(json.dumps({"ok": False, "error": "canonical cube missing"}))
            return
        try:
            hooks = json.loads(row[2] or "[]")
        except Exception:
            hooks = []
        if not isinstance(hooks, list):
            hooks = []
        if not any(isinstance(h, dict) and h.get("when") == HOOK["when"] for h in hooks):
            hooks.append(HOOK)
        fields = {
            "topic": row[3],
            "essence": row[4],
            "rules": row[0] + RULES_ADD,
            "skill_md": (row[1] or "") + SKILL_ADD,
            "hooks": hooks,
            "kind": row[5] or "moment",
            "carrier": row[6] or "skill",
            "diff": {"added_steps": ["scrub", "requirements", "skill_md+hooks", "dedup", "publish or confirm"],
                     "added_hooks": [HOOK["when"]], "req_delta": {}},
        }
        out = dd.propose_version(conn, CANON, fields, MARK + ": skill import path and first-connection hook", row[7])
        if out.get("cube_id"):
            conn.execute("UPDATE cubes_new SET links_json=? WHERE cube_id=?",
                         (json.dumps({"supersedes": CANON, "court": True, "mark": MARK, "diff": fields["diff"]}), out["cube_id"]))
        status = conn.execute("SELECT status FROM cubes_new WHERE cube_id=?", (CANON,)).fetchone()
        conn.commit()
        print(json.dumps({"ok": bool(out.get("ok")), "cube_id": out.get("cube_id"), "canonical_status": status[0] if status else ""}))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
