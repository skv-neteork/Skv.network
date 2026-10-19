#!/usr/bin/env python3
"""Courier and watch. Not the old evolver. Drains court_queue. Alerts only when the server is sick."""
import json, os, sqlite3, urllib.request
from datetime import datetime

DB = "/data/skv/metadata_store/shared_master.db"
LOG = "/tmp/skv_evolver.log"

def log(msg):
    line = datetime.now().strftime("%Y-%m-%d %H:%M:%S") + " " + msg
    print(line)
    open(LOG, "a").write(line + "\n")

def key():
    for line in open("/root/skv-core/.env"):
        if line.startswith("POLZA_KEY="):
            return line.split("=", 1)[1].strip()
    return ""

CONST = "Constitution: do no harm. Do not invent. A cube must change the obvious answer and name the trap and the instead. Banal steps are a fail. Empty or harmful is remove. Generic advice any person or model already gives (drink water, be careful, test your code) changes nothing: remove."

VERDICTS = ("keep", "fix", "remove")
J1, J2, J3 = "deepseek/deepseek-chat", "meta-llama/llama-3.3-70b-instruct", "qwen/qwen3.6-plus"   # qwen often answers with prose: last resort only


def _post(model, content, max_tokens, json_mode):
    body = {"model": model, "messages": [{"role": "user", "content": content}], "temperature": 0, "max_tokens": max_tokens}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    req = urllib.request.Request("https://api.polza.ai/v1/chat/completions", data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "Authorization": "Bearer " + key(), "User-Agent": "skv-evolver"})
    return (json.loads(urllib.request.urlopen(req, timeout=90).read())["choices"][0]["message"].get("content") or "").strip()


def _strict_json(text):
    try:
        d = json.loads(text)
    except Exception:
        return None
    v = str(d.get("verdict", "")).strip().lower() if isinstance(d, dict) else ""
    return {"verdict": v, "reason": str(d.get("reason", ""))[:200]} if v in VERDICTS else None


def _strict_line(text):
    import re
    m = re.fullmatch(r"\s*VERDICT:\s*(keep|fix|remove)\s*(?:\|\s*(.*))?", text.strip().splitlines()[0] if text.strip() else "", re.I)
    return {"verdict": m.group(1).lower(), "reason": (m.group(2) or "")[:200]} if m else None


def ask(model, prompt):
    """Strict verdict or None (abstain). Try 1: JSON mode. Try 2: one-line format. Nothing else is guessed."""
    try:
        r = _strict_json(_post(model, prompt + "\nDecide yourself. verdict is exactly one of: keep, fix, remove. Reply with JSON only, e.g. {\"verdict\": \"<your verdict>\", \"reason\": \"<why, under 12 words>\"}", 120, True))
        if r:
            return r
    except Exception as e:
        log("judge json fail " + model + " " + str(e)[:60])
    try:
        return _strict_line(_post(model, prompt + "\nReply with exactly one line and nothing else: VERDICT: keep|fix|remove | short reason", 60, False))
    except Exception as e:
        log("judge line fail " + model + " " + str(e)[:60])
        return None


def judge(title, rules):
    prompt = CONST + "\nTITLE: " + title + "\nRULES:\n" + rules[:900]
    first = ask(J1, prompt)
    if not first:
        return {"votes": [(J1, "abstain", "unparsed")], "rules": "", "skip": True}
    votes = [(J1, first["verdict"], first["reason"])]
    if first["verdict"] == "remove":
        # A delete needs a clear second "remove". Unparsed = abstain (never keep); then a third model decides.
        second = ask(J2, prompt)
        votes.append((J2, second["verdict"], second["reason"]) if second else (J2, "abstain", "unparsed"))
        if not second:
            third = ask(J3, prompt)
            votes.append((J3, third["verdict"], third["reason"]) if third else (J3, "abstain", "unparsed"))
    removers = {j for j, v, _ in votes if v == "remove"}
    rules_out = ""
    if len(removers) < 2 and any(v in ("fix", "remove") for _, v, _ in votes):
        rules_out = _post(J1, "Rewrite as 4 short rules. Name the trap and the instead. No commentary.\n" + rules[:800], 180, False)
    return {"votes": votes, "rules": rules_out}


def drain():
    c = sqlite3.connect(DB)
    c.execute("CREATE TABLE IF NOT EXISTS court_queue (cube_id TEXT PRIMARY KEY, reason TEXT, created_at TEXT)")
    rows = c.execute("SELECT cube_id FROM court_queue").fetchall()
    for (cid,) in rows:
        cube = c.execute("SELECT essence, rules_markdown, is_constitutional FROM cubes_new WHERE cube_id=?", (cid,)).fetchone()
        if not cube or cube[2]:
            c.execute("DELETE FROM court_queue WHERE cube_id=?", (cid,))
            log("skip " + cid)
            continue
        try:
            verdict = judge(cube[0] or cid, cube[1] or "")
        except Exception as e:
            log("judge fail " + cid + " " + str(e)[:80])
            continue
        if verdict.get("skip"):
            log("first judge abstained, retry next night " + cid)
            continue
        import importlib.util as _iu
        _sp = _iu.spec_from_file_location("cubes_v2", "/root/skv-core/src/app/cubes_v2.py"); cv = _iu.module_from_spec(_sp); _sp.loader.exec_module(cv)
        cv.ensure(c)
        v = cv.apply_verdicts(c, cid, verdict["votes"])   # remove = archive, only with two judges
        if v == "fix" and (verdict.get("rules") or "").strip():
            c.execute("UPDATE cubes_new SET rules_markdown=?, status=\"community\" WHERE cube_id=?", ((verdict.get("rules") or "")[:4000], cid))
        elif v != "remove":
            c.execute("UPDATE cubes_new SET status=\"community\" WHERE cube_id=? AND status NOT IN ('archived','quarantine')", (cid,))
        c.execute("DELETE FROM court_queue WHERE cube_id=?", (cid,))
        log(cid + " " + v + " " + str(verdict.get("votes"))); note(cid + " " + v)
    c.commit()
    c.close()


def note(line):
    open("/tmp/skv_digest.txt", "a").write(datetime.now().strftime("%H:%M") + " " + line + "\n")

def send_digest():
    path = "/tmp/skv_digest.txt"
    stamp = "/tmp/skv_digest.sent"
    today = datetime.now().strftime("%Y-%m-%d")
    if os.path.exists(stamp) and open(stamp).read().strip() == today:
        return
    if not os.path.exists(path) or not open(path).read().strip():
        return
    body = open(path).read()
    mail("SKV day", body)
    open(path, "w").write("")
    open(stamp, "w").write(today)

def mail(subject, body):
    try:
        rkey = ""
        for line in open("/root/skv-core/.env"):
            if line.startswith("RESEND_API_KEY="):
                rkey = line.split("=", 1)[1].strip()
        if not rkey:
            return
        req = urllib.request.Request(
            "https://api.resend.com/emails",
            data=json.dumps({"from": "SKV Network <noreply@skv.network>", "to": ["denizchavdarov@gmail.com"], "subject": subject, "text": body}).encode(),
            headers={"Authorization": "Bearer " + rkey, "Content-Type": "application/json", "User-Agent": "skv-evolver"},
        )
        urllib.request.urlopen(req, timeout=20).read()
        log("mailed " + subject)
    except Exception as e:
        log("mail fail " + str(e)[:120])


def new_users():
    import sqlite3
    seen = "/tmp/skv_users.seen"
    last = open(seen).read().strip() if os.path.exists(seen) else "1970-01-01"
    c = sqlite3.connect("/data/skv/metadata_store/shared_master.db")
    rows = c.execute("select email, confirmed, created_at from users where created_at > ? order by created_at", (last,)).fetchall()
    c.close()
    if not rows:
        return
    for email, confirmed, created in rows:
        note("new user " + email + " confirmed=" + str(confirmed))
    open(seen, "w").write(rows[-1][2])

def watch():
    sick = []
    try:
        used = int(os.popen("df / | awk \"NR==2{print \\$5}\" | tr -d %").read() or "0")
        if used >= 90:
            sick.append("disk " + str(used))
    except Exception:
        sick.append("disk unreadable")
    try:
        avail = int(os.popen("free -m | awk \"NR==2{print \\$7}\"").read() or "0")
        if avail < 80:
            sick.append("ram " + str(avail))
    except Exception:
        sick.append("ram unreadable")
    up = os.popen("docker ps --format {{.Names}}").read()
    if "skv_api" not in up:
        sick.append("api down")
    try:
        code = os.popen("curl -s -o /dev/null -w %{http_code} https://skv.network/").read().strip()
        if code != "200":
            sick.append("home " + code)
    except Exception:
        sick.append("home fail")
    if sick:
        log("ALERT " + ", ".join(sick)); mail("SKV server", ", ".join(sick))
    else:
        log("server ok")

if __name__ == "__main__":
    drain()
    new_users()
    watch()
    send_digest()
