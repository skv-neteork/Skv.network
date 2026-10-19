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

CONST = "Constitution: do no harm. Do not invent. A cube must change the obvious answer and name the trap and the instead. Banal steps are a fail. Empty or harmful is remove."

def _parse(msg):
    text = msg.get("content") or msg.get("reasoning") or ""
    if "{" not in text:
        return {"verdict": "fix", "reason": text[:80]}
    return json.loads(text[text.find("{"):text.rfind("}") + 1])

def ask(model, prompt):
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.2, "max_tokens": 250}).encode()
    req = urllib.request.Request("https://api.polza.ai/v1/chat/completions", data=body, headers={"Content-Type": "application/json", "Authorization": "Bearer " + key(), "User-Agent": "skv-evolver"})
    msg = json.loads(urllib.request.urlopen(req, timeout=60).read())["choices"][0]["message"]
    return _parse(msg)

def judge(title, rules):
    prompt = CONST + "\nReply only JSON {\"verdict\":\"keep\"|\"fix\"|\"remove\",\"reason\":\"short\"}.\nTITLE: " + title + "\nRULES:\n" + rules[:900]
    vote = ask("deepseek/deepseek-chat", prompt)
    votes = [("deepseek/deepseek-chat", (vote.get("verdict") or "fix").lower(), vote.get("reason", ""))]
    # A delete needs a second judge. One model must not erase a cube alone (cubes_v2.apply_verdicts enforces it).
    if votes[0][1] == "remove":
        second = ask("qwen/qwen3.6-plus", prompt)
        votes.append(("qwen/qwen3.6-plus", (second.get("verdict") or "fix").lower(), second.get("reason", "")))
    rules_out = ""
    if any(v[1] != "keep" for v in votes) and not (len(votes) == 2 and all(v[1] == "remove" for v in votes)):
        fix = "Rewrite as 4 short rules. Name the trap and the instead. No commentary.\n" + rules[:800]
        body = json.dumps({"model": "deepseek/deepseek-chat", "messages": [{"role": "user", "content": fix}], "temperature": 0.2, "max_tokens": 180}).encode()
        req = urllib.request.Request("https://api.polza.ai/v1/chat/completions", data=body, headers={"Content-Type": "application/json", "Authorization": "Bearer " + key(), "User-Agent": "skv-evolver"})
        msg = json.loads(urllib.request.urlopen(req, timeout=60).read())["choices"][0]["message"]
        rules_out = msg.get("content") or ""
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
