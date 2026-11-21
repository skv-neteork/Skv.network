"""Dry-run list of test-alias and smoke cubes in the shared pool.

Prints ids and counts. Does not DELETE. Does not read or print an API key.
"""
import os
import sqlite3

SHARED = os.environ.get("SKV_SHARED_DB", "/data/skv/metadata_store/shared_master.db")
REPORT = os.environ.get("SKV_PURGE_REPORT", "/root/skv-tasks/notebook_purge_dry_run.txt")

SQL = """
SELECT cube_id, coalesce(created_by,''), coalesce(subject_action_object,''), coalesce(status,''), coalesce(kind,'')
FROM cubes_new
WHERE lower(coalesce(created_by,'')) LIKE '%skvext%'
   OR lower(coalesce(subject_action_object,'')) LIKE '%zq%srch%'
   OR lower(coalesce(evidence,'')) LIKE '%zq%srch%'
   OR lower(coalesce(subject_action_object,'')) LIKE 'smoke hooks %'
   OR lower(coalesce(subject_action_object,'')) LIKE 'smoke merge %'
ORDER BY cube_id
"""


def main():
    lines = ["dry-run only: no DELETE", "db: %s" % SHARED]
    if not os.path.isfile(SHARED):
        lines.append("missing database")
        _write(lines)
        return 0
    c = sqlite3.connect("file:%s?mode=ro" % SHARED, uri=True, timeout=10)
    try:
        rows = c.execute(SQL).fetchall()
    finally:
        c.close()
    by_author = {}
    for cid, author, topic, status, kind in rows:
        by_author[author] = by_author.get(author, 0) + 1
        lines.append("%s\t%s\t%s\t%s\t%s" % (cid, status, kind, author, topic[:80].replace("\n", " ")))
    lines.append("count: %d" % len(rows))
    for author, n in sorted(by_author.items(), key=lambda x: (-x[1], x[0])):
        lines.append("by_created_by %d %s" % (n, author))
    _write(lines)
    return 0


def _write(lines):
    text = "\n".join(lines) + "\n"
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(text, end="")


if __name__ == "__main__":
    raise SystemExit(main())
