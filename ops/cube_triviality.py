#!/usr/bin/env python3
"""Triviality sweep for shared cubes (cubes v2). Judge 1: llama-3.1-8b. A 'trivial' verdict is archived only if
judge 2 (llama-3.3-70b) agrees. Archive = copy to cubes_archive + status archived; never a hard delete.
Usage: python3 ops/cube_triviality.py [--apply] [--limit N]"""
import json, sqlite3, sys, urllib.request, importlib.util
DB = "/data/skv/metadata_store/shared_master.db"
sp = importlib.util.spec_from_file_location("cubes_v2", "/root/skv-core/src/app/cubes_v2.py"); cv = importlib.util.module_from_spec(sp); sp.loader.exec_module(cv)
KEY = next(l.split("=", 1)[1].strip() for l in open("/root/skv-core/.env") if l.startswith("POLZA_KEY="))
J1, J2 = "meta-llama/llama-3.1-8b-instruct", "meta-llama/llama-3.3-70b-instruct"
RULE = ("SKV rule: a cube is useful only if it changes the obvious answer an AI would give: working code, a lifehack, a warning naming a trap, "
        "a concrete fact/number/command the model would not know, or a craft rule. Generic advice anyone would give (e.g. 'boil an egg', "
        "'be careful', 'test your code'), empty text, or a restatement of a question is TRIVIAL.\n"
        "Reply only JSON {\"verdict\":\"useful\"|\"trivial\",\"reason\":\"<12 words\"}.")
usage = {"in": 0, "out": 0}
def ask(model, text):
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": RULE + "\n\nCUBE:\n" + text[:1500]}], "temperature": 0, "max_tokens": 60}).encode()
    r = json.loads(urllib.request.urlopen(urllib.request.Request("https://api.polza.ai/v1/chat/completions", body,
        {"Content-Type": "application/json", "Authorization": "Bearer " + KEY, "User-Agent": "skv-triviality"}), timeout=60).read())
    u = r.get("usage") or {}; usage["in"] += u.get("prompt_tokens", 0); usage["out"] += u.get("completion_tokens", 0)
    usage["cost"] = usage.get("cost", 0) + float(u.get("cost", 0) or 0)
    t = r["choices"][0]["message"].get("content") or ""
    try:
        return json.loads(t[t.find("{"):t.rfind("}") + 1])
    except Exception:
        return {"verdict": "useful", "reason": "unparsed"}
def main():
    apply = "--apply" in sys.argv
    lim = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 10**6
    c = sqlite3.connect(DB); cv.ensure(c)
    rows = c.execute("""SELECT cube_id, subject_action_object, essence, rules_markdown FROM cubes_new WHERE status NOT IN ('archived','removed','quarantine')
        AND COALESCE(is_constitutional,0)=0 AND cube_id NOT LIKE 'cube_const_%' AND COALESCE(kind,'moment') NOT IN ('help_request','project','project_node')
        AND triviality IS NULL LIMIT ?""", (lim,)).fetchall()
    res = {"checked": 0, "trivial": [], "kept_by_judge2": []}
    for cid, topic, ess, rules in rows:
        text = "TOPIC: %s\nESSENCE: %s\nRULES: %s" % (topic, ess, rules)
        v1 = ask(J1, text); res["checked"] += 1
        if v1.get("verdict") == "trivial":
            v2 = ask(J2, text)
            if v2.get("verdict") == "trivial":
                res["trivial"].append((cid, ess[:70], v1.get("reason"), v2.get("reason")))
                if apply:
                    cv.apply_verdicts(c, cid, [(J1, "remove", "trivial: " + str(v1.get("reason"))), (J2, "remove", "trivial: " + str(v2.get("reason")))])
                    c.execute("UPDATE cubes_new SET triviality=? WHERE cube_id=?", ("trivial: " + str(v1.get("reason"))[:100], cid))
                continue
            res["kept_by_judge2"].append((cid, ess[:70]))
        if apply:
            c.execute("UPDATE cubes_new SET triviality='ok' WHERE cube_id=?", (cid,))
        c.commit()
    c.commit()
    res["usage"] = usage
    print(json.dumps(res, ensure_ascii=False, indent=1))
main()
