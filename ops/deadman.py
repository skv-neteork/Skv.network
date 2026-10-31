#!/usr/bin/env python3
"""SKV dead-man check (T05). Cron: */15 server, daily 09:00 MSK backup.
One mail per incident + one recovery mail. Server needs 2 failed runs in a row (no restart blips).
State: /var/lib/skv/deadman.json (persists over reboot). Env: DEADMAN_STATE, DEADMAN_DRYRUN=1, DEADMAN_API_URL, DEADMAN_BACKUP_GLOB."""
import os, sys, json, glob, time, urllib.request
from datetime import datetime, timezone, timedelta
MSK = timezone(timedelta(hours=3))
STATE = os.environ.get("DEADMAN_STATE", "/var/lib/skv/deadman.json")
API = os.environ.get("DEADMAN_API_URL", "http://127.0.0.1:8000/api/v7/health")
BGLOB = os.environ.get("DEADMAN_BACKUP_GLOB", "/root/skv_offsite/*.tar.gz.gpg")
TO = "denizchavdarov@gmail.com"

def now(): return datetime.now(MSK).strftime("%Y-%m-%d %H:%M MSK")
def log(m): print(now(), m, flush=True)

def load():
    try: return json.load(open(STATE))
    except Exception: return {}
def save(s):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump(s, open(STATE + ".tmp", "w"), indent=1); os.replace(STATE + ".tmp", STATE)

def mail(subject, body):
    if os.environ.get("DEADMAN_DRYRUN"):
        log("DRYRUN mail: " + subject); return True
    key = ""
    for line in open("/root/skv-core/.env"):
        if line.startswith("RESEND_API_KEY="): key = line.split("=", 1)[1].strip()
    req = urllib.request.Request("https://api.resend.com/emails",
        data=json.dumps({"from": "SKV Network <noreply@skv.network>", "to": [TO], "subject": subject, "text": body}).encode(),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json", "User-Agent": "skv-deadman"})
    try:
        urllib.request.urlopen(req, timeout=20).read(); log("mailed " + subject); return True
    except Exception as e:
        log("mail fail " + str(e)[:150]); return False

def probe_api():
    try:
        urllib.request.urlopen(API, timeout=10); return None
    except urllib.error.HTTPError as e:
        return None if e.code < 500 else "HTTP %d" % e.code   # 401 = app alive
    except Exception as e:
        return "no answer (%s)" % str(e)[:80]

def probe_backup():
    f = sorted(glob.glob(BGLOB), key=os.path.getmtime)
    if not f: return "no backup files"
    age = (time.time() - os.path.getmtime(f[-1])) / 3600
    return None if age <= 26 else "last backup %s is %.0fh old" % (os.path.basename(f[-1]), age)

def step(s, name, err, need=1):
    st = s.setdefault(name, {"fails": 0, "open": False})
    if err:
        st["fails"] += 1; st["last_err"] = err
        log("%s FAIL %d: %s" % (name, st["fails"], err))
        if not st["open"] and st["fails"] >= need:
            if mail("SKV ALERT: %s down" % name, "%s\n%s: %s\nOne mail per incident; you get a recovery mail when it is back." % (now(), name, err)):
                st["open"] = True; st["since"] = now()
    else:
        if st["open"]:
            if mail("SKV recovered: %s" % name, "%s\n%s is ok again (incident since %s)." % (now(), name, st.get("since"))):
                st["open"] = False
        st["fails"] = 0
        if not st["open"]: log(name + " ok")

if __name__ == "__main__":
    s = load()
    if "--server" in sys.argv or len(sys.argv) == 1: step(s, "server", probe_api(), need=2)
    if "--backup" in sys.argv or len(sys.argv) == 1: step(s, "backup", probe_backup())
    save(s)
