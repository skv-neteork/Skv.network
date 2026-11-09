#!/usr/bin/env python3
"""Git pre-commit: refuse a foreign file claim, a deleted def/class, or a wholesale rewrite.

ALLOW-DELETE: <reason> in the commit message waives the delete and rewrite checks.
A file claimed by another agent is still refused.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from app.room.diffcheck import _hunks, review_diff


def _diff():
    return subprocess.check_output(["git", "diff", "--cached", "--unified=3"], text=True, errors="replace")


def _message():
    msg = os.environ.get("SKV_COMMIT_MSG") or ""
    if msg:
        return msg
    git_dir = subprocess.check_output(["git", "rev-parse", "--git-dir"], text=True).strip()
    path = os.path.join(git_dir, "COMMIT_EDITMSG")
    if os.path.isfile(path):
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    return ""


def _claimed():
    raw = os.environ.get("SKV_CLAIMED_BY_OTHER") or ""
    return [ln.strip() for ln in raw.splitlines() if ln.strip()]


def _head_sizes(diff_text):
    """Line counts at HEAD. The 30% and 80% checks are about the file, not the diff window."""
    sizes = {}
    for item in _hunks(diff_text):
        path = item["path"]
        try:
            text = subprocess.check_output(["git", "show", "HEAD:%s" % path], stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            continue
        sizes[path] = len(text.splitlines()) or 1
    return sizes


def main():
    diff = _diff()
    report = review_diff(diff, _message(), _claimed(), _head_sizes(diff))
    if report["ok"]:
        return 0
    sys.stderr.write("\n".join(report["errors"]) + "\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
