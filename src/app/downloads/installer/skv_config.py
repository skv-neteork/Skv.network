#!/usr/bin/env python3
"""SKV config editor used by install.sh / install.ps1. Merges or removes SKV entries in agent configs.
Never touches other entries. Backs up every file it changes (<file>.skv-bak.<timestamp>).
usage: skv_config.py install|uninstall <client> <skv_home> <base>
"""
import json, os, shutil, sys, time, platform

NAME = "skv"
MARK = "skv_hook.py"
HOOKS_ON = os.environ.get("SKV_NO_HOOKS", "0") in ("", "0")


def load(p):
    if not os.path.exists(p):
        return {}
    with open(p, encoding="utf-8") as f:
        t = f.read().strip()
    return json.loads(t) if t else {}


def save(p, d, private=False):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    if os.path.exists(p):
        b = p + ".skv-bak." + time.strftime("%Y%m%d%H%M%S")
        shutil.copy2(p, b)
        print("  backup:", b)
    tmp = p + ".skv-tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)
        f.write("\n")
    if private:
        os.chmod(tmp, 0o600)
    elif os.path.exists(p):
        shutil.copymode(p, tmp)
    os.replace(tmp, p)
    print("  wrote:", p)


def py():
    return sys.executable if platform.system() == "Windows" else "python3"


def hook_cmd(home, mode, shell="sh"):
    """Command string that works in the client's hook shell. Forward slashes work in PowerShell, cmd and Git Bash."""
    win = platform.system() == "Windows"
    exe = sys.executable.replace("\\", "/") if win else "python3"
    h = os.path.join(home, "skv_hook.py").replace("\\", "/")
    if " " not in exe and " " not in h:
        return "%s %s %s" % (exe, h, mode)
    cmd = '"%s" "%s" %s' % (exe, h, mode)
    return ("& " + cmd) if (win and shell == "powershell") else cmd


def desktop_path():
    s = platform.system()
    if s == "Darwin":
        return os.path.expanduser("~/Library/Application Support/Claude/claude_desktop_config.json")
    if s == "Windows":
        return os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "Claude", "claude_desktop_config.json")
    return os.path.expanduser("~/.config/Claude/claude_desktop_config.json")


def strip_hooks(lst):
    out = []
    for grp in lst or []:
        hs = [h for h in grp.get("hooks", []) if MARK not in str(h.get("command", ""))]
        if hs:
            g = dict(grp); g["hooks"] = hs; out.append(g)
    return out


def main():
    act, client, home, base = sys.argv[1:5]
    key = ""
    if act == "install":
        with open(os.path.join(home, "key"), encoding="utf-8") as f:
            key = f.read().strip()
    mcp_url = base.rstrip("/") + "/mcp"
    auth = {"Authorization": "Bearer " + key}

    if client == "claude-code":
        p = os.path.expanduser("~/.claude.json")           # user-scope MCP servers
        d = load(p)
        d.setdefault("mcpServers", {})
        if act == "install":
            d["mcpServers"][NAME] = {"type": "http", "url": mcp_url, "headers": auth}
        else:
            d["mcpServers"].pop(NAME, None)
        save(p, d, private=True)
        p = os.path.expanduser("~/.claude/settings.json")  # hooks
        d = load(p)
        hk = d.setdefault("hooks", {})
        for ev, mode in (("UserPromptSubmit", "claude-prompt"), ("Stop", "claude-stop")):
            hk[ev] = strip_hooks(hk.get(ev))
            if act == "install" and HOOKS_ON:
                hk[ev].append({"hooks": [{"type": "command", "command": hook_cmd(home, mode), "timeout": 30}]})
            if not hk[ev]:
                hk.pop(ev)
        if not hk:
            d.pop("hooks")
        save(p, d)

    elif client == "cursor":
        p = os.path.expanduser("~/.cursor/mcp.json")
        d = load(p)
        d.setdefault("mcpServers", {})
        if act == "install":
            d["mcpServers"][NAME] = {"url": mcp_url, "headers": auth}
        else:
            d["mcpServers"].pop(NAME, None)
        save(p, d, private=True)
        p = os.path.expanduser("~/.cursor/hooks.json")
        d = load(p)
        d.setdefault("version", 1)
        hk = d.setdefault("hooks", {})
        for ev, mode in (("beforeSubmitPrompt", "cursor-prompt"), ("afterAgentResponse", "cursor-response")):
            hk[ev] = [h for h in hk.get(ev, []) if MARK not in str(h.get("command", ""))]
            if act == "install" and HOOKS_ON:
                hk[ev].append({"command": hook_cmd(home, mode, "powershell"), "timeout": 30})
            if not hk[ev]:
                hk.pop(ev)
        save(p, d)

    elif client == "claude-desktop":
        # Claude Desktop config only launches local (stdio) servers: bridge to the remote MCP with mcp-remote (needs Node.js).
        # No hooks in Claude Desktop: saving relies on the agent calling turn (MCP instructions).
        p = desktop_path()
        d = load(p)
        d.setdefault("mcpServers", {})
        if act == "install":
            d["mcpServers"][NAME] = {"command": "npx", "args": ["-y", "mcp-remote", mcp_url, "--header", "Authorization:${SKV_AUTH}"],
                                     "env": {"SKV_AUTH": "Bearer " + key}}
        else:
            d["mcpServers"].pop(NAME, None)
        save(p, d, private=True)
    else:
        sys.exit("unknown client " + client)


if __name__ == "__main__":
    main()
