#!/usr/bin/env python3
"""SKV hook for local agents: saves each turn (last user message + answer) via POST /api/v7/agent/turn
and returns the server seal. Installed by https://skv.network/install.sh. Never blocks the agent (fail-open).

Modes (argv[1]):
  claude-prompt   Claude Code UserPromptSubmit: remember the user message, remind the agent to call turn
  claude-stop     Claude Code Stop: save turn (user msg + last_assistant_message), show seal
  cursor-prompt   Cursor beforeSubmitPrompt: remember the user message
  cursor-response Cursor afterAgentResponse: save turn
  cursor-stop     Cursor stop: with the stop guard on, one follow-up message when no SKV turn was called
  test            send a test turn, print the seal
Key: ~/.skv/key (0600) or SKV_API_KEY. Off switch: touch ~/.skv/off (or uninstall).

STOP GUARD (ON by default since the installer creates ~/.skv/guard; opt out: install.sh --no-stop-guard or rm ~/.skv/guard): the Stop hook blocks the end of a reply when no SKV
turn was called for the current user message (no seal in the answer and no turn tool call after the last user message).
Claude Code and Grok Build get {"decision":"block","reason":...}; Cursor gets {"followup_message":...} from its stop event.
At most 2 blocks per user message, then the old fallback runs (the hook saves the turn itself). Fail-open on any error.
Grok Build reads ~/.claude/settings.json and ~/.cursor/hooks.json too: camelCase fields (sessionId, lastAssistantMessage,
stopHookActive, reason) are accepted next to the snake_case ones.
"""
import json, os, re, sys, time, urllib.request, hashlib

HOME = os.path.expanduser("~")
D = os.environ.get("SKV_HOME") or os.path.join(HOME, ".skv")
BASE = (os.environ.get("SKV_BASE") or "https://skv.network").rstrip("/")
SEAL_RE = re.compile(r"(?:🔐\s*)?SKV\s*\|\s*#\d+·[0-9a-f]{4}")
TIMEOUT = 20
REMIND = ("SKV: before you answer, call the skv MCP tool turn(user_message, draft) and end the answer "
          "with the seal it returns. If the tool is unavailable, answer normally (the Stop hook saves the turn).")
MAX_BLOCKS = 2
GUARD_REASON = ("SKV: no turn was called for the current user message. Call the skv MCP tool turn(user_message=<the user's "
                "message>, msg_ref=<its id>, draft=<your answer>) now, in this step, then finish the reply with the seal it "
                "returns. turn is called in the same first step as the first reply to every user message, however short; "
                "the seal at the end is the user's visible check.")
TURN_TOOL_RE = re.compile(r"(?:^|__|\.|/)turn$")


def guard_on():
    return os.environ.get("SKV_STOP_GUARD") == "1" or os.path.exists(os.path.join(D, "guard"))


def ev_get(ev, *names):
    """First non-empty field: Claude Code snake_case, Grok Build and Cursor camelCase/snake_case."""
    for n in names:
        v = ev.get(n)
        if v not in (None, ""):
            return v
    return ""


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
        json.dump({"prompt": prompt, "t": time.time(), "blocks": 0}, f)
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


def load_state(sid):
    try:
        with open(state_path(sid), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def update_state(sid, **kw):
    st = load_state(sid)
    st.update(kw)
    p = state_path(sid)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(st, f)
    try:
        os.chmod(p, 0o600)
    except Exception:
        pass
    return st


def turn_called_in_transcript(path):
    """Claude Code JSONL: True when an assistant tool_use named like <server>__turn follows the last real user message."""
    called = False
    try:
        with open(os.path.expanduser(path), encoding="utf-8") as f:
            for line in f:
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                m = o.get("message") or {}
                c = m.get("content")
                if o.get("type") == "user" and m.get("role") == "user":
                    if isinstance(c, str):
                        called = False
                    elif isinstance(c, list) and any(isinstance(x, dict) and x.get("type") == "text" and (x.get("text") or "").strip() for x in c):
                        called = False
                elif o.get("type") == "assistant" and isinstance(c, list):
                    for x in c:
                        if isinstance(x, dict) and x.get("type") == "tool_use" and TURN_TOOL_RE.search(str(x.get("name") or "")) \
                                and "skv" in str(x.get("name") or "").lower():
                            called = True
    except Exception:
        return False
    return called


def guard_verdict(sid, answer, transcript_path=""):
    """None = let the reply finish. A string = block with that reason (at most MAX_BLOCKS per user message)."""
    if not guard_on() or os.path.exists(os.path.join(D, "off")):
        return None
    if SEAL_RE.search(answer or ""):
        return None
    if transcript_path and turn_called_in_transcript(transcript_path):
        return None
    st = load_state(sid)
    n = int(st.get("blocks") or 0)
    if n >= MAX_BLOCKS:
        log("stop guard: gave up after %d blocks, fallback save" % n)
        return None
    update_state(sid, blocks=n + 1)
    log("stop guard: blocked (%d)" % (n + 1))
    return GUARD_REASON


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
        remember_prompt(ev_get(ev, "session_id", "sessionId"), ev.get("prompt") or "")
        if not os.path.exists(os.path.join(D, "off")):   # per-prompt reminder (stdout -> agent context)
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": REMIND}}))
    elif mode == "claude-stop":
        if os.environ.get("CURSOR_VERSION"):
            return
        if ev.get("reason") not in (None, "", "end_turn"):   # Grok Build also fires Stop at session end
            return
        sid = ev_get(ev, "session_id", "sessionId")
        tp = ev_get(ev, "transcript_path", "transcriptPath")
        answer = ev_get(ev, "last_assistant_message", "lastAssistantMessage") or ""
        why = guard_verdict(sid, answer, tp)
        if why:
            print(json.dumps({"decision": "block", "reason": why}, ensure_ascii=False))
            return
        um = recall_prompt(sid) or last_user_from_transcript(tp)
        seal = save(um, answer, "hook:claude_code", sid)
        if seal:
            print(json.dumps({"systemMessage": seal}, ensure_ascii=False))
    elif mode == "cursor-prompt":
        remember_prompt(ev.get("conversation_id"), ev.get("prompt") or "")
        print(json.dumps({"continue": True}))
    elif mode == "cursor-response":
        sid = ev.get("conversation_id") or ""
        text = ev.get("text") or ""
        if guard_on() and not os.path.exists(os.path.join(D, "off")):
            # the stop event decides: block once, or save as the fallback
            update_state(sid, last_answer=text[:60000], sealed=bool(SEAL_RE.search(text)))
        else:
            save(recall_prompt(sid), text, "hook:cursor", sid)
        print("{}")
    elif mode == "cursor-stop":
        sid = ev.get("conversation_id") or ""
        if not sid or not guard_on() or os.path.exists(os.path.join(D, "off")):   # Grok Build has no conversation_id: claude-stop covers it
            print("{}")
            return
        st = load_state(sid)
        if ev.get("status") not in (None, "", "completed"):
            print("{}")
            return
        if st.get("sealed") or not (st.get("last_answer") or "").strip():
            print("{}")
            return
        n = int(st.get("blocks") or 0)
        if n < MAX_BLOCKS and int(ev.get("loop_count") or 0) < MAX_BLOCKS:
            update_state(sid, blocks=n + 1)
            log("stop guard (cursor): follow-up (%d)" % (n + 1))
            print(json.dumps({"followup_message": GUARD_REASON}, ensure_ascii=False))
            return
        save(st.get("prompt") or "", st.get("last_answer") or "", "hook:cursor", sid)
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
