#!/usr/bin/env python3
"""SKV hook for local agents: saves each turn (last user message + answer) via POST /api/v7/agent/turn
and returns the server seal. Installed by https://skv.network/install.sh. Never blocks the agent (fail-open).

Modes (argv[1]):
  claude-prompt   Claude Code UserPromptSubmit: remember the user message
  claude-stop     Claude Code Stop: save turn (user msg + last_assistant_message), show seal
  cursor-prompt   Cursor beforeSubmitPrompt: remember the user message
  cursor-response Cursor afterAgentResponse: save turn
  test            send a test turn, print the seal
Key: ~/.skv/key (0600) or SKV_API_KEY. Off switch: touch ~/.skv/off (or uninstall).
"""
import json, os, re, sys, time, urllib.request, hashlib

HOME = os.path.expanduser("~")
D = os.environ.get("SKV_HOME") or os.path.join(HOME, ".skv")
BASE = (os.environ.get("SKV_BASE") or "https://skv.network").rstrip("/")
SEAL_RE = re.compile(r"(?:🔐\s*)?SKV\s*\|\s*#\d+·[0-9a-f]{4}")
TIMEOUT = 20


def log(msg):
    try:
        with open(os.path.join(D, "hook.log"), "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except Exception:
        pass


def key():
    k = (os.environ.get("SKV_API_KEY") or "").strip()
    if k:
        return k
    try:
        with open(os.path.join(D, "key"), encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def state_path(sid):
    sd = os.path.join(D, "state")
    os.makedirs(sd, mode=0o700, exist_ok=True)
    return os.path.join(sd, hashlib.sha256((sid or "default").encode()).hexdigest()[:16] + ".json")


def remember_prompt(sid, prompt):
    p = state_path(sid)
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"prompt": prompt, "t": time.time()}, f)
    try:
        os.chmod(p, 0o600)
    except Exception:
        pass


def recall_prompt(sid):
    try:
        with open(state_path(sid), encoding="utf-8") as f:
            return json.load(f).get("prompt") or ""
    except Exception:
        return ""


def last_user_from_transcript(path):
    """Fallback: last real user text in a Claude Code JSONL transcript."""
    last = ""
    try:
        with open(os.path.expanduser(path), encoding="utf-8") as f:
            for line in f:
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                m = o.get("message") or {}
                if o.get("type") != "user" or m.get("role") != "user":
                    continue
                c = m.get("content")
                if isinstance(c, str):
                    last = c
                elif isinstance(c, list):
                    t = " ".join(x.get("text", "") for x in c if isinstance(x, dict) and x.get("type") == "text")
                    if t.strip():
                        last = t
    except Exception:
        pass
    return last


def send_turn(user_message, answer, source, sid):
    k = key()
    if not k:
        log("no key")
        return None
    body = json.dumps({"user_message": user_message[:20000], "draft": answer[:60000], "compact": True,
                       "session_id": ("hook-" + (sid or ""))[:64], "source": source}).encode()
    req = urllib.request.Request(BASE + "/api/v7/agent/turn", data=body, method="POST",
                                 headers={"Authorization": "Bearer " + k, "Content-Type": "application/json",
                                          "User-Agent": "skv-hook/1.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def save(user_message, answer, source, sid):
    if os.path.exists(os.path.join(D, "off")):
        return None
    if not answer.strip():
        return None
    if SEAL_RE.search(answer):          # agent already called turn itself via MCP: don't double-save
        log(source + " skip: answer already sealed")
        return None
    if not user_message.strip():
        user_message = "(user message not captured)"
    try:
        d = send_turn(user_message, answer, source, sid) or {}
    except Exception as e:
        log(source + " error: " + type(e).__name__)
        return None
    seal = d.get("seal")
    log("%s verdict=%s seal=%s" % (source, d.get("verdict"), seal))
    return seal


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    raw = "" if mode == "test" else sys.stdin.read()
    try:
        ev = json.loads(raw) if raw.strip() else {}
    except Exception:
        ev = {}
    if mode == "claude-prompt":
        if os.environ.get("CURSOR_VERSION"):   # Cursor also runs Claude Code hooks: Cursor has its own
            return
        remember_prompt(ev.get("session_id"), ev.get("prompt") or "")
    elif mode == "claude-stop":
        if os.environ.get("CURSOR_VERSION"):
            return
        sid = ev.get("session_id") or ""
        um = recall_prompt(sid) or last_user_from_transcript(ev.get("transcript_path") or "")
        seal = save(um, ev.get("last_assistant_message") or "", "hook:claude_code", sid)
        if seal:
            print(json.dumps({"systemMessage": seal}, ensure_ascii=False))
    elif mode == "cursor-prompt":
        remember_prompt(ev.get("conversation_id"), ev.get("prompt") or "")
        print(json.dumps({"continue": True}))
    elif mode == "cursor-response":
        sid = ev.get("conversation_id") or ""
        save(recall_prompt(sid), ev.get("text") or "", "hook:cursor", sid)
        print("{}")
    elif mode == "test":
        seal = save("SKV installer test: are hooks connected?", "Yes - this is the SKV installer test turn.",
                    "hook:installer_test", "installer-test")
        print(("SKV seal: " + seal) if seal else "SKV test FAILED (see ~/.skv/hook.log)")
        sys.exit(0 if seal else 1)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # fail-open: never break the agent
        log("fatal " + type(e).__name__)
