#!/usr/bin/env python3
"""Profile migration helper (dry-run by default). Runs INSIDE skv_api:
  docker exec -i skv_api python - <uid> [--out /tmp/x.json] < ops/profile_migrate.py
Proposes profile ops from critical facts (critical_auto) that look like rules about
HOW to work with the user. Import mode: <uid> --import FILE.json [--report X.md] (list of {text,kind,source_hint}).
Nothing is written unless --apply --i-confirm (needs Deniz's go)."""
import sys, json, re, sqlite3
sys.path.insert(0, "/app")
from app import profile
SIG = re.compile(r"(никогда|всегда|не надо|не делай|запрещ|правило|предпочит|хочу чтобы|never|always|don't|do not|prefer|must|rule)", re.I)
def main(a):
    uid = a[0]; out = a[a.index("--out") + 1] if "--out" in a else None
    db = profile._db(uid) if hasattr(profile, "_db") else None
    if db is None:
        from app import shelves; db = shelves.connect(uid)
    ops = []
    for k, kind, val, ctx, eid in db.execute("select key,kind,value,context,event_id from critical_auto"):
        t = (val or "").strip()
        if t and SIG.search(t + " " + (ctx or "")):
            ops.append({"op": "add", "kind": "rule", "text": t[:300], "scope": "global", "src_key": k, **({"ev": [eid]} if eid else {"ev": ["unlinked"], "unlinked_reason": "critical fact without a source event"})})
    res = {"user_id": uid, "candidates": len(ops), "ops": ops}
    if "--apply" in a:
        if "--i-confirm" not in a:
            sys.exit("refuse: --apply needs --i-confirm (and Deniz's approval)")
        res["apply"] = profile.import_ops(uid, ops, dry_run=False)
    else:
        res["dry_run"] = profile.import_ops(uid, ops, dry_run=True)
    s = json.dumps(res, ensure_ascii=False, indent=1)
    open(out, "w").write(s) if out else print(s)
# ─── import mode: --import FILE.json [--report PATH.md] (dry-run only unless --apply --i-confirm) ───
OBS = re.compile(r"(obsolete|outdated|deprecated|no longer|not anymore|used to|old:|устар|больше не|уже не|раньше|было:|отменен|неактуал)", re.I)
RULE_KINDS = {"rule", "preference", "prohibition", "style", "workflow", "profile", "instruction", "habit"}
FACT_KINDS = {"fact", "world", "world_fact", "project", "person", "event", "info"}
def _classify(it):
    t = (it.get("text") or "") + " " + (it.get("source_hint") or ""); k = (it.get("kind") or "").lower().strip()
    if k == "obsolete" or OBS.search(t):
        return "obsolete", "kind/obsolete marker" if k == "obsolete" else "obsolete wording: " + OBS.search(t).group(0)
    if k in RULE_KINDS: return "profile_rule", "kind=" + k
    if k in FACT_KINDS and not SIG.search(it.get("text") or ""): return "world_fact", "kind=" + k
    if SIG.search(it.get("text") or ""): return "profile_rule", "rule wording: " + SIG.search(it["text"]).group(0)
    return "world_fact", "no rule wording" + (" (kind=%s)" % k if k else "")
def _find_source(uid, db, it):
    q = ((it.get("text") or "") + " " + (it.get("source_hint") or "")).strip()[:300]
    hits = []
    try:
        from app import search_v2
        hits = [e for e, _s in search_v2.hybrid(uid, q, top_k=6)[0]]
    except Exception as e:
        try:
            from app import search_v2
            hits = [e for e, _s in search_v2.fts_ranked(uid, q, limit=6)[0]]
        except Exception as e2:
            return None, 0.0, "search failed: %s" % str(e2)[:80]
    best, bs, _raw = None, 0.0, ""
    for eid in hits:
        try:
            r = db.execute("SELECT raw_dialogue FROM event_metadata WHERE event_id=?", (eid,)).fetchone()
        except Exception:
            r = None
        if not r: continue
        sc = max(profile._jacc(it.get("text"), r[0] or ""), _cover(it.get("text"), r[0] or ""))
        if sc > bs: best, bs, _raw = eid, sc, r[0] or ""
    if best and bs >= 0.5 and len(profile._toks(it.get("text")) & profile._toks(_raw)) >= 2:
        return best, bs, ""
    return None, bs, ("no matching event (best overlap %.2f)" % bs) if hits else "memory search found nothing"
def _cover(a, b):
    ta, tb = profile._toks(a), profile._toks(b)
    return len(ta & tb) / float(len(ta) or 1)
def _conf(a, b):
    pa, pb = profile._polarity(a), profile._polarity(b)
    ta = profile._toks(profile._NEG.sub(" ", profile._POS.sub(" ", a))); tb = profile._toks(profile._NEG.sub(" ", profile._POS.sub(" ", b)))
    return bool(pa and pb and pa != pb and len(ta & tb) / float(min(len(ta), len(tb)) or 1) >= 0.6)
def import_mode(a):
    uid = a[0]; f = a[a.index("--import") + 1]
    rep = a[a.index("--report") + 1] if "--report" in a else "/tmp/profile_import_review.md"
    items = json.load(open(f))
    if isinstance(items, dict): items = items.get("items") or items.get("rows") or []
    db = profile._db(uid)
    try: act = profile._active(db)
    except Exception: act = []
    res = []
    for i, it in enumerate(items):
        it = it if isinstance(it, dict) else {"text": str(it)}
        t = (it.get("text") or "").strip()
        cls, why = _classify(it)
        r = {"n": i + 1, "text": t, "kind_in": it.get("kind"), "hint": it.get("source_hint"), "class": cls, "why": why, "issues": []}
        if not t: r["class"] = "skip"; r["issues"].append("empty text"); res.append(r); continue
        s = profile.secret_hit(t)
        if s: r["issues"].append("contains a secret-like value (%s): would be rejected" % s)
        ev, sc, reason = _find_source(uid, db, it)
        r["ev"], r["score"], r["unlinked_reason"] = ev, round(sc, 2), reason
        for p in res:
            if p["class"] == "skip": continue
            if _conf(t, p["text"]): r["issues"].append("conflicts with #%d" % p["n"])
            elif profile._jacc(t, p["text"]) >= 0.6: r["issues"].append("duplicate of #%d" % p["n"])
        for row in act:
            if _conf(t, row["text"]): r["issues"].append("conflicts with active prof:%s" % row["id"])
            elif profile._jacc(t, row["text"]) >= 0.6: r["issues"].append("duplicate of active prof:%s" % row["id"])
        res.append(r)
    prom = {int(x) for x in a[a.index("--promote") + 1].split(",")} if "--promote" in a else set()
    for r in res:
        if r["n"] in prom and r["class"] != "profile_rule":
            r["class"], r["why"] = "profile_rule", "promoted by Deniz (was %s: %s)" % (r["class"], r["why"])
    ops = [{"op": "add", "kind": "rule", "text": r["text"][:300], "scope": "global",
            **({"ev": [r["ev"]]} if r["ev"] else {"ev": ["unlinked"], "unlinked_reason": "from Grok Bot memory, pre-SKV or not matched (" + (r["unlinked_reason"] or "no source") + ")"})}
           for r in res if r["class"] == "profile_rule" and not any(x.startswith(("duplicate", "contains")) for x in r["issues"])]
    def _batched(dry_run):
        agg = {"dry_run": dry_run, "n_ops": len(ops), "batches": 0, "errors": [], "linked": 0, "unlinked": 0}
        for i in range(0, len(ops), 10):   # server limit: 10 profile ops per call
            d = profile.import_ops(uid, ops[i:i + 10], dry_run=dry_run); agg["batches"] += 1
            agg["errors"] += ["batch %d: %s" % (i // 10 + 1, e) for e in (d.get("errors") or [])]
            agg["linked"] += int(d.get("linked") or 0); agg["unlinked"] += int(d.get("unlinked") or 0)
        return agg
    dry = _batched(True)
    from collections import Counter
    cc = Counter(r["class"] for r in res)
    L = ["# Profile import review — %s" % uid, "", "Source: `%s`; generated %s; **dry run, nothing applied**." % (f, profile._now() if hasattr(profile, "_now") else ""), "",
         "## Summary", "", "- items: %d" % len(res)] + ["- %s: %d" % (k, v) for k, v in sorted(cc.items())] + [
         "- linked to a source event: %d; unlinked: %d" % (sum(1 for r in res if r.get("ev")), sum(1 for r in res if r["class"] != "skip" and not r.get("ev"))),
         "- duplicates: %d; conflicts: %d; secrets: %d" % (sum(any(x.startswith("duplicate") for x in r["issues"]) for r in res), sum(any(x.startswith("conflicts") for x in r["issues"]) for r in res), sum(any(x.startswith("contains") for x in r["issues"]) for r in res)),
         "- proposed profile ops: %d; import_ops dry-run: `%s`" % (len(ops), json.dumps(dry, ensure_ascii=False)[:300]), "",
         "## Items", "", "| # | class | why | source | issues | text |", "|---|---|---|---|---|---|"]
    for r in res:
        src = ("ev:%s (%.2f)" % (r["ev"].split("::")[-1], r["score"])) if r.get("ev") else ("unlinked: " + (r.get("unlinked_reason") or ""))
        L.append("| %d | %s | %s | %s | %s | %s |" % (r["n"], r["class"], r["why"], src, "; ".join(r["issues"]) or "", r["text"].replace("|", "\\|").replace("\n", " ")[:220]))
    L += ["", "World facts and obsolete items are NOT imported into the profile (facts stay in memory). Apply only after review: `--import FILE --apply --i-confirm`."]
    open(rep, "w").write("\n".join(L) + "\n")
    out = {"report": rep, "counts": dict(cc), "ops": len(ops), "items": res, "dry_run": dry}
    if "--apply" in a:
        if "--i-confirm" not in a: sys.exit("refuse: --apply needs --i-confirm (and Deniz's approval)")
        out["apply"] = _batched(False)
    print(json.dumps(out, ensure_ascii=False, indent=1))

if __name__ == "__main__":
    (import_mode if "--import" in sys.argv else main)(sys.argv[1:])
