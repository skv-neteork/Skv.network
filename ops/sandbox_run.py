#!/usr/bin/env python3
"""SKV safe sandbox launcher (host). stdin JSON {code, language, files{name:text}} -> stdout JSON {stdout, stderr, exit_code, timed_out}.
Fixed flags only; the caller controls nothing but code/language/files."""
import json, subprocess, sys, uuid
IMG = "skv_sandbox_safe:1"; TIMEOUT = 15; CAP = 16000
BOOT = r'''
import json,os,sys,subprocess,re
d=json.load(sys.stdin)
for n,t in (d.get("files") or {}).items():
    n=os.path.basename(n)
    if n: open(n,"w").write(t)
lang=d.get("language","python")
if lang=="node": open("main.js","w").write(d["code"]); cmd=["node","main.js"]
elif lang=="pytest": open("test_main.py","w").write(d["code"]); cmd=["python","-m","pytest","-q","-p","no:cacheprovider"]
else:
    t=bool(re.search(r"^def test_",d["code"],re.M))
    open("test_main.py" if t else "main.py","w").write(d["code"])
    cmd=["python","-m","pytest","-q","-p","no:cacheprovider"] if t else ["python","main.py"]
os.execvp(cmd[0],cmd)
'''
def main():
    d = json.load(sys.stdin)
    lang = d.get("language") or "python"
    if lang not in ("python", "pytest", "node"):
        print(json.dumps({"error": "language must be python|pytest|node"})); return
    payload = json.dumps({"code": str(d.get("code") or "")[:100000], "language": lang,
                          "files": {str(k)[:64]: str(v)[:100000] for k, v in list((d.get("files") or {}).items())[:10]}})
    name = "skvsb_" + uuid.uuid4().hex[:12]
    cmd = ["docker", "run", "-i", "--rm", "--name", name, "--network", "none", "--read-only",
           "--tmpfs", "/work:rw,nosuid,nodev,size=32m,uid=10001", "--tmpfs", "/tmp:rw,nosuid,nodev,size=16m,uid=10001",
           "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--user", "10001:10001",
           "--pids-limit", "64", "--memory", "256m", "--memory-swap", "256m", "--cpus", "0.5",
           "--ulimit", "nofile=256:256", "--ulimit", "fsize=10000000", "-e", "HOME=/work", "-w", "/work",
           IMG, "python", "-c", BOOT]
    to = False
    try:
        p = subprocess.run(cmd, input=payload.encode(), capture_output=True, timeout=TIMEOUT)
        out, err, rc = p.stdout, p.stderr, p.returncode
    except subprocess.TimeoutExpired as e:
        subprocess.run(["docker", "kill", name], capture_output=True)
        out, err, rc, to = e.stdout or b"", (e.stderr or b"") + b"\n[killed: timeout %ds]" % TIMEOUT, 124, True
    def cut(b):
        s = b.decode("utf-8", "replace")
        return s if len(s) <= CAP else s[:CAP] + "\n[output cut at %d chars]" % CAP
    print(json.dumps({"stdout": cut(out), "stderr": cut(err), "exit_code": rc, "timed_out": to}))
main()
