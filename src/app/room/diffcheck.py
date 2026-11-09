"""Pre-commit checks: foreign file claim, mass delete, wholesale rewrite."""
import re

_DEF = re.compile(r"^[\t ]*(?:async[\t ]+def|def|class)[\t ]+([A-Za-z_][A-Za-z0-9_]*)", re.M)
_ALLOW = re.compile(r"ALLOW-DELETE:\s*\S+")


def _hunks(diff_text):
    files = []
    cur = None
    for line in (diff_text or "").splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            path = parts[-1][2:] if len(parts) >= 4 and parts[-1].startswith("b/") else parts[-1]
            cur = {"path": path, "deleted": [], "added": [], "old": 0, "new": 0}
            files.append(cur)
            continue
        if cur is None:
            continue
        if line.startswith("+++ ") or line.startswith("--- ") or line.startswith("index ") or line.startswith("@@"):
            continue
        if line.startswith("-"):
            cur["deleted"].append(line[1:])
        elif line.startswith("+"):
            cur["added"].append(line[1:])
        elif line.startswith("\\"):
            continue
        else:
            # context
            body = line[1:] if line.startswith(" ") else line
            cur["old"] += 1
            cur["new"] += 1
    for f in files:
        f["old"] += len(f["deleted"])
        f["new"] += len(f["added"])
    return files


def _names(lines):
    return set(_DEF.findall("\n".join(lines)))


def review_diff(diff_text, message="", claimed_by_other_paths=None, old_sizes=None):
    """Return {ok, errors}. ALLOW-DELETE: <reason> waives delete and wholesale-rewrite, not a foreign claim."""
    claimed = set()
    for p in claimed_by_other_paths or []:
        claimed.add(p.replace("\\", "/").lstrip("./"))
    allow = bool(_ALLOW.search(message or ""))
    errors = []
    for f in _hunks(diff_text):
        path = f["path"]
        norm = path.replace("\\", "/")
        if norm in claimed or path in claimed:
            errors.append("claimed by another agent: %s" % path)
        old_n = int((old_sizes or {}).get(path) or (old_sizes or {}).get(norm) or f["old"] or 0)
        deleted_n = len(f["deleted"])
        if not allow and old_n and deleted_n / old_n > 0.30:
            errors.append("deleted >30%% of %s" % path)
        removed = _names(f["deleted"]) - _names(f["added"])
        if not allow and removed:
            errors.append("def/class deleted: %s" % ", ".join(sorted(removed)))
        if not allow and old_n > 300 and old_n and deleted_n / old_n > 0.80:
            errors.append("rewrote >80%% of %s (%d lines)" % (path, old_n))
    return {"ok": not errors, "errors": errors}
