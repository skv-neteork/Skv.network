"""Delayed recall ('вспомнилось позже' / deep_search).

POST /memory/recall_later {user_id, query} queues a background job:
  cheap LLM agent on the server runs 5–30 lens/search/focus steps,
  writes a report WITH sources (ids, dates, notes), stores it,
  delivers once later in /memory as 'remembered' (after recall_later_delay),
  and is always available via GET /memory/recall_later/{job_id}.

Trigger: agent requests deep_search, or fast /search returns no_confident_match.

Config: recall_later_enabled, recall_later_tokens (400), recall_later_delay (3),
recall_later_model (falls back to llm_model), recall_later_max_cost_rub (3.0),
recall_later_max_steps (15, clamped 5..30), recall_later_min_steps (5).
"""
import json, re, secrets, threading, time
from app import shelves as _sh
from app.memory_v2 import clip, config, est_tokens, mask_text, norm_date

_LOCK = threading.Lock()

_SYSTEM = (
    "Ты — исследователь личной памяти SKV. Ищешь только через инструменты, факты не выдумываешь.\n"
    "Отвечай ТОЛЬКО одним JSON-объектом, без markdown и без текста вокруг.\n"
    "Действия:\n"
    '{"action":"search","query":"короткий поисковый запрос"}\n'
    '{"action":"focus","event_id":"uid::...","query":"зачем углубиться"}\n'
    '{"action":"more","query":"тот же или уточнённый","cursor":N}\n'
    '{"action":"done","found":true|false,"summary":"краткий отчёт на языке вопроса",'
    '"sources":[{"id":"...","date":"YYYY-MM-DD","note":"..."}],'
    '"lines":[{"id":"...","text":"одно короткое предложение с датой"}]}\n'
    "Правила: id только из наблюдений; lines ≤ 3; sources ≤ 8; если ничего нет — "
    "found:false, summary честно говорит что не нашёл, sources/lines пустые. "
    "Сначала search по разным формулировкам (RU/EN, синонимы, имена), потом focus на лучшие эпизоды. Когда готово — сразу done: summary ≤ 400 символов, notes в sources ≤ 80 символов, lines ≤ 2 коротких предложений."
)


def _conn(uid):
    c = _sh.connect(uid)
    c.execute("""CREATE TABLE IF NOT EXISTS recall_later (
                 job_id TEXT PRIMARY KEY, query TEXT, status TEXT, created_at REAL,
                 created_n INTEGER, ready_at REAL, delivered_at REAL, lines_json TEXT,
                 expanded_json TEXT, cost_rub REAL, error TEXT)""")
    c.execute("CREATE TABLE IF NOT EXISTS recall_later_state (id INTEGER PRIMARY KEY CHECK (id=1), n INTEGER)")
    cols = {r[1] for r in c.execute("PRAGMA table_info(recall_later)")}
    for col, decl in (
        ("report_json", "TEXT"),
        ("steps_json", "TEXT"),
        ("progress", "TEXT"),
        ("steps_n", "INTEGER"),
    ):
        if col not in cols:
            c.execute(f"ALTER TABLE recall_later ADD COLUMN {col} {decl}")
    c.commit()
    return c


def _n(c):
    r = c.execute("SELECT n FROM recall_later_state WHERE id=1").fetchone()
    return r[0] if r else 0


def _llm(messages, max_tokens):
    from app import memory_v2_llm as L
    import os, urllib.request
    cfg = config()
    model = cfg.get("recall_later_model") or cfg.get("llm_model") or "meta-llama/llama-3.1-8b-instruct"
    req = urllib.request.Request(
        L.URL,
        data=json.dumps({
            "model": model, "messages": messages, "temperature": 0.1, "max_tokens": max_tokens,
        }).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + os.environ.get("POLZA_KEY", "")},
    )
    with urllib.request.urlopen(req, timeout=90) as r:
        d = json.loads(r.read())
    u = d.get("usage") or {}
    cost = u.get("cost_rub", d.get("cost_rub", u.get("cost", d.get("cost")))) or 0
    L._log({"ts": time.time(), "job": "recall_later", "model": model,
            "prompt": u.get("prompt_tokens", 0), "completion": u.get("completion_tokens", 0),
            "cost_rub": cost})
    return d["choices"][0]["message"]["content"], float(cost or 0), model


def _json(s):
    if not s:
        return {}
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    a, b = s.find("{"), s.rfind("}")
    if a >= 0 and b > a:
        chunk = s[a:b + 1]
        try:
            return json.loads(chunk)
        except Exception:
            m2 = re.search(r"\{[\s\S]*?\"action\"[\s\S]*?\}", chunk)
            if m2:
                try:
                    return json.loads(m2.group(0))
                except Exception:
                    pass
    return {}


def _set_progress(uid, jid, text, **extra):
    c = _conn(uid)
    try:
        c.execute("UPDATE recall_later SET progress=? WHERE job_id=?", (str(text)[:240], jid))
        if "steps_n" in extra:
            c.execute("UPDATE recall_later SET steps_n=? WHERE job_id=?", (int(extra["steps_n"]), jid))
        c.commit()
    finally:
        c.close()


def _clip_obs(obs, budget=3500):
    """Keep newest observations within a token budget for the agent prompt."""
    kept, used = [], 0
    for o in reversed(obs):
        t = est_tokens(o)
        if kept and used + t > budget:
            break
        kept.append(o)
        used += t
    kept.reverse()
    return kept


def _fmt_lens(out, cap=1200):
    """Compact lens/search result for the agent."""
    if not out:
        return "пусто"
    clusters = out.get("clusters") or []
    lines = [f"terms={out.get('terms')}; hits={out.get('total_hits')}; clusters={out.get('clusters_total')}; more={out.get('more_cursor')}"]
    for i, cl in enumerate(clusters[:5]):
        center = cl.get("center") or cl.get("event") or {}
        eid = center.get("event_id") or cl.get("event_id") or ""
        date = norm_date(center.get("date") or center.get("time_str") or cl.get("period") or "")[:10]
        preview = mask_text(clip(center.get("text") or cl.get("preview") or cl.get("summary") or "", 70))
        l1 = mask_text(clip(cl.get("l1") or "", 40))
        l2 = mask_text(clip(cl.get("l2") or "", 40))
        mt = center.get("match_type") or cl.get("match_type") or ""
        lines.append(f"C{i+1} [{mt}] {date} id={eid} :: {preview}")
        if l1:
            lines.append(f"  L1: {l1}")
        if l2:
            lines.append(f"  L2: {l2}")
        for side in ("before", "after"):
            for n in (cl.get(side) or [])[:2]:
                lines.append(
                    f"  {side}: {norm_date(n.get('date') or n.get('time_str') or '')[:10]} "
                    f"{n.get('event_id','')} :: {mask_text(clip(n.get('text') or '', 40))}"
                )
    return clip("\n".join(lines), max(200, cap // 4))


def _collect_ids(obs_text):
    return set(re.findall(r"[\w.+@-]+::[\w.:-]+", obs_text or "")) | set(
        re.findall(r"\bid=([\w.+@-]+::[\w.:-]+)", obs_text or "")
    )


def _lens_search(uid, query, cursor=0, focus_event_id=None):
    from app import memory_v2_lens as lens
    budget = int(config().get("budgets", {}).get("lens", 1500) or 1500)
    return lens.lens(uid, query, budget=budget, focus_event_id=focus_event_id,
                     radius=2, offset=int(cursor or 0))


def _seed_searches(uid, query):
    """Deterministic first steps so a weak model still gathers evidence."""
    from app import memory_v2_lens as lens
    bodies = lens._scan(uid)
    rare, _ = lens.query_terms(query, bodies)
    variants = [query]
    if rare:
        variants.append(" ".join(t["term"] for t in rare[:4]))
    # also try English-ish tokens if any latin words present
    latin = " ".join(re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", query))
    if latin and latin.lower() not in query.lower():
        variants.append(latin)
    out, seen = [], set()
    for q in variants:
        q = (q or "").strip()
        if len(q) < 2 or q.lower() in seen:
            continue
        seen.add(q.lower())
        try:
            res = _lens_search(uid, q)
            out.append((q, res))
        except Exception as e:
            out.append((q, {"error": str(e)[:120]}))
        if len(out) >= 3:
            break
    # archive step 2: old period, or lens found nothing -> keyword search in event_archive (raw text >90 days)
    try:
        from app import archive_recall as _ar
        empty = all(not (isinstance(r, dict) and (r.get("hits") or r.get("results") or r.get("text") or r.get("lines"))) for _, r in out)
        if empty or _ar.is_old(query):
            ah = _ar.search(uid, query, limit=6)
            if ah:
                out.append(("archive:" + query, {"archive": True, "note": "archived raw text (>90 days)",
                                                 "text": "\n".join("id=%s [%s] (archived) %s" % (a["event_id"], a["time_str"], a["snippet"]) for a in ah)}))
    except Exception:
        pass
    return out



def _report_from_obs(query, observations, known_ids):
    """Deterministic fallback report from lens observations when the LLM fails."""
    sources, lines = [], []
    # pull id + preview lines like: C1 [..] DATE id=EID :: PREVIEW
    for obs in observations:
        for m in re.finditer(
            r"C\d+ \[[^\]]*\] (\d{4}-\d{2}-\d{2})?\s*id=([\w.@+-]+::[\w.:-]+) :: (.+)",
            obs,
        ):
            date, eid, prev = m.group(1) or "", m.group(2), m.group(3).strip()
            if eid in known_ids or "::" in eid:
                if not any(s["id"] == eid for s in sources):
                    sources.append({"id": eid, "date": date, "note": mask_text(prev)[:120]})
                if len(lines) < 3 and prev:
                    lines.append({"id": eid, "text": mask_text(f"{date}: {prev}")[:240]})
            if len(sources) >= 5:
                break
        if len(sources) >= 5:
            break
    found = bool(sources)
    summary = (
        f"По линзе нашлось {len(sources)} эпизод(ов) по запросу «{clip(query, 40)}» "
        f"(запасной отчёт без модели)."
        if found else
        f"Ничего надёжного по запросу «{clip(query, 40)}» в наблюдениях линзы не видно."
    )
    return {"found": found, "summary": summary, "sources": sources[:8], "lines": lines[:3]}


def submit(uid, query):
    query = mask_text((query or "").strip())[:500]
    if len(query) < 2:
        raise ValueError("query required")
    jid = "rl_" + secrets.token_hex(8)
    c = _conn(uid)
    try:
        if c.execute(
            "SELECT COUNT(*) FROM recall_later WHERE status IN ('queued','running') AND created_at > ?",
            (time.time() - 900,),
        ).fetchone()[0] >= 3:
            raise OverflowError("too many recall_later jobs running")
        c.execute(
            "INSERT INTO recall_later (job_id, query, status, created_at, created_n, progress, steps_n) VALUES (?,?,?,?,?,?,?)",
            (jid, query, "queued", time.time(), _n(c), "queued", 0),
        )
        c.commit()
    finally:
        c.close()
    threading.Thread(target=run, args=(uid, jid), daemon=True).start()
    return jid


def run(uid, jid):
    from app import inflight
    cfg = config()
    cap = float(cfg.get("recall_later_max_cost_rub", 3.0))
    max_steps = max(5, min(30, int(cfg.get("recall_later_max_steps", 15) or 15)))
    min_steps = max(1, min(max_steps, int(cfg.get("recall_later_min_steps", 5) or 5)))
    cost = 0.0
    steps_log = []
    observations = []
    known_ids = set()
    lines, expanded, err = [], [""], None
    report = {"found": False, "summary": "", "sources": [], "lines": [], "steps": 0}

    c = _conn(uid)
    q = c.execute("SELECT query FROM recall_later WHERE job_id=?", (jid,)).fetchone()[0]
    c.execute("UPDATE recall_later SET status='running', progress=? WHERE job_id=?", ("running", jid))
    c.commit()
    c.close()
    expanded = [q]

    with inflight.track("recall_later"):
        try:
            _set_progress(uid, jid, "seed lens search", steps_n=0)
            for sq, res in _seed_searches(uid, q):
                if isinstance(res, dict) and res.get("error"):
                    obs = f"search({sq!r}) ERROR: {res['error']}"
                else:
                    obs = f"search({sq!r}):\n{_fmt_lens(res)}"
                    known_ids |= _collect_ids(obs)
                    # auto-focus top cluster once
                    clusters = (res or {}).get("clusters") or []
                    if clusters:
                        center = clusters[0].get("center") or {}
                        fe = center.get("event_id") or clusters[0].get("event_id")
                        if fe:
                            try:
                                foc = _lens_search(uid, q, focus_event_id=fe)
                                fobs = f"focus({fe}):\n{_fmt_lens(foc)}"
                                observations.append(fobs)
                                known_ids |= _collect_ids(fobs)
                                steps_log.append({"action": "focus", "event_id": fe, "ok": True})
                            except Exception as e:
                                steps_log.append({"action": "focus", "event_id": fe, "error": str(e)[:100]})
                observations.append(obs)
                steps_log.append({"action": "search", "query": sq, "ok": True})
                _set_progress(uid, jid, f"seed:{sq[:60]}", steps_n=len(steps_log))
                if len(steps_log) >= min_steps:
                    break

            # agent loop
            while len(steps_log) < max_steps and cost < cap:
                obs_block = "\n---\n".join(_clip_obs(observations))
                user = (
                    f"Вопрос: {q}\nШаг {len(steps_log)+1}/{max_steps}. Потрачено ~{cost:.3f}₽ из {cap}₽.\n"
                    f"Уже сделано действий: {len(steps_log)} (минимум до done: {min_steps}).\n"
                    f"Известные id (фрагмент): {', '.join(list(known_ids)[:20]) or '-'}\n\n"
                    f"Наблюдения:\n{obs_block}\n\n"
                    f"Выбери следующее действие JSON."
                )
                if len(steps_log) < min_steps:
                    user += " Ещё рано завершать found=false — сделай search/focus."
                try:
                    txt, k, _model = _llm(
                        [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}],
                        1200,
                    )
                    cost += k
                except Exception as e:
                    err = f"llm:{e}"[:200]
                    break
                act = _json(txt)
                action = (act.get("action") or "").lower().strip()
                if action not in ("search", "focus", "more", "done"):
                    # treat as done-attempt if it looks like a report
                    if "summary" in act or "found" in act:
                        action = "done"
                    else:
                        steps_log.append({"action": "parse_fail", "raw": mask_text(str(txt)[:200])})
                        observations.append("PARSE_FAIL: ответь строго одним JSON action.")
                        _set_progress(uid, jid, "parse_fail", steps_n=len(steps_log))
                        if len(steps_log) >= max_steps - 1:
                            action = "done"
                            act = {"found": False, "summary": "Модель не смогла завершить поиск корректно.", "sources": [], "lines": []}
                        else:
                            continue

                if action == "search":
                    sq = mask_text(str(act.get("query") or q))[:200]
                    if len(sq) < 2:
                        sq = q
                    if sq not in expanded:
                        expanded.append(sq)
                    try:
                        res = _lens_search(uid, sq)
                        obs = f"search({sq!r}):\n{_fmt_lens(res)}"
                        known_ids |= _collect_ids(obs)
                        steps_log.append({"action": "search", "query": sq})
                    except Exception as e:
                        obs = f"search({sq!r}) ERROR: {e}"
                        steps_log.append({"action": "search", "query": sq, "error": str(e)[:100]})
                    observations.append(obs)

                elif action == "more":
                    sq = mask_text(str(act.get("query") or q))[:200]
                    cur = int(act.get("cursor") or 0)
                    try:
                        res = _lens_search(uid, sq, cursor=cur)
                        obs = f"more({sq!r}, cursor={cur}):\n{_fmt_lens(res)}"
                        known_ids |= _collect_ids(obs)
                        steps_log.append({"action": "more", "query": sq, "cursor": cur})
                    except Exception as e:
                        obs = f"more ERROR: {e}"
                        steps_log.append({"action": "more", "error": str(e)[:100]})
                    observations.append(obs)

                elif action == "focus":
                    fe = str(act.get("event_id") or "").strip()
                    if fe and not fe.startswith(uid.split("@")[0][:3]) and "::" not in fe:
                        # allow only ids we have seen, or that look like event ids
                        pass
                    if fe not in known_ids and "::" in fe:
                        # still try if it looks like an event id for this user db naming
                        known_ids.add(fe)
                    if not fe or "::" not in fe:
                        observations.append("focus ERROR: нужен event_id из наблюдений")
                        steps_log.append({"action": "focus", "error": "missing id"})
                    else:
                        try:
                            res = _lens_search(uid, str(act.get("query") or q)[:200], focus_event_id=fe)
                            obs = f"focus({fe}):\n{_fmt_lens(res)}"
                            known_ids |= _collect_ids(obs)
                            steps_log.append({"action": "focus", "event_id": fe})
                        except Exception as e:
                            obs = f"focus ERROR: {e}"
                            steps_log.append({"action": "focus", "event_id": fe, "error": str(e)[:100]})
                        observations.append(obs)

                elif action == "done":
                    if len(steps_log) < min_steps and cost < cap * 0.9:
                        observations.append(
                            f"SYSTEM: слишком рано для done (шагов {len(steps_log)} < {min_steps}). "
                            "Сделай ещё search или focus."
                        )
                        steps_log.append({"action": "done_rejected_early"})
                        _set_progress(uid, jid, "done_rejected_early", steps_n=len(steps_log))
                        continue
                    if act.get("_truncated") or not str(act.get("summary") or "").strip():
                        try:
                            obs_block = "\n---\n".join(_clip_obs(observations, 2500))
                            txt2, k2, _m2 = _llm(
                                [{"role": "system", "content": _SYSTEM},
                                 {"role": "user", "content": (
                                     f"Вопрос: {q}\nСделай КОРОТКИЙ action=done (summary≤400 символов).\n"
                                     f"Наблюдения:\n{obs_block}"
                                 )}],
                                900,
                            )
                            cost += k2
                            act = _json(txt2)
                            act["action"] = "done"
                            steps_log.append({"action": "done_retry_short"})
                        except Exception as e:
                            steps_log.append({"action": "done_retry_fail", "error": str(e)[:80]})
                    report = _finalize_report(act, known_ids, q)
                    lines = report.get("lines") or []
                    steps_log.append({"action": "done", "found": report.get("found")})
                    break

                _set_progress(uid, jid, f"{action}:{len(steps_log)}", steps_n=len(steps_log))

            else:
                # exhausted steps/budget — force a final report from the model once
                if not report.get("summary"):
                    obs_block = "\n---\n".join(_clip_obs(observations, 2800))
                    try:
                        txt, k, _model = _llm(
                            [
                                {"role": "system", "content": _SYSTEM},
                                {"role": "user", "content": (
                                    f"Вопрос: {q}\nЛимит шагов/бюджета исчерпан. Сейчас ОБЯЗАТЕЛЬНО action=done.\n"
                                    f"Наблюдения:\n{obs_block}"
                                )},
                            ],
                            1200,
                        )
                        cost += k
                        report = _finalize_report(_json(txt), known_ids, q)
                        lines = report.get("lines") or []
                        steps_log.append({"action": "done_forced", "found": report.get("found")})
                    except Exception as e:
                        err = (err or "") + f"|final:{e}"[:180]
                        report = {
                            "found": False,
                            "summary": "Не удалось завершить отчёт: ошибка модели.",
                            "sources": [],
                            "lines": [],
                        }

            if (not (report.get("summary") or "").strip()
                    or "не смогла завершить" in (report.get("summary") or "").lower()
                    or report.get("_truncated")):
                report = _report_from_obs(q, observations, known_ids)
                lines = report.get("lines") or []
                steps_log.append({"action": "fallback_report", "found": report.get("found")})
            report["steps"] = len(steps_log)
            report["cost_rub"] = round(cost, 4)
            report["expanded"] = expanded
        except Exception as e:
            err = str(e)[:200]
            print(f"[recall_later] {jid} failed: {e}", flush=True)
            report = report if report.get("summary") else {
                "found": False, "summary": f"Ошибка: {err}", "sources": [], "lines": [],
            }

    # persist
    c = _conn(uid)
    c.execute(
        "UPDATE recall_later SET status=?, ready_at=?, lines_json=?, expanded_json=?, cost_rub=?, "
        "error=?, report_json=?, steps_json=?, progress=?, steps_n=? WHERE job_id=?",
        (
            "error" if err and not report.get("summary") else "done",
            time.time(),
            json.dumps(lines, ensure_ascii=False),
            json.dumps(expanded, ensure_ascii=False),
            round(cost, 4),
            err,
            json.dumps(report, ensure_ascii=False),
            json.dumps(steps_log, ensure_ascii=False),
            "done" if not err else f"error:{err[:80]}",
            len(steps_log),
            jid,
        ),
    )
    # if we have a usable report, mark done even with soft err
    if report.get("summary") and err:
        c.execute("UPDATE recall_later SET status='done' WHERE job_id=?", (jid,))
    c.commit()
    c.close()


def _finalize_report(act, known_ids, query):
    """Keep only sources/lines whose ids were observed (no guessing)."""
    found = bool(act.get("found"))
    summary = mask_text(str(act.get("summary") or "").strip())[:1200]
    sources, lines = [], []
    for s in (act.get("sources") or [])[:8]:
        if not isinstance(s, dict):
            continue
        sid = str(s.get("id") or "").strip()
        if sid and sid not in known_ids and not sid.startswith("l1:") and not sid.startswith("l2:"):
            continue
        if sid or s.get("note"):
            sources.append({
                "id": sid,
                "date": norm_date(str(s.get("date") or ""))[:10],
                "note": mask_text(str(s.get("note") or ""))[:200],
            })
    for l in (act.get("lines") or [])[:3]:
        if not isinstance(l, dict) or not l.get("text"):
            continue
        lid = str(l.get("id") or "").strip()
        if lid and lid not in known_ids and not lid.startswith("l1:") and not lid.startswith("l2:"):
            continue
        lines.append({"id": lid, "text": mask_text(str(l["text"]))[:240]})
    if not summary:
        summary = ("Нашёл релевантные фрагменты." if (found or lines or sources)
                   else "Ничего надёжного в памяти не нашлось.")
    if not lines and not sources:
        found = False
    return {"found": found, "summary": summary, "sources": sources, "lines": lines}


def get(uid, jid):
    c = _conn(uid)
    try:
        cols = ("job_id", "query", "status", "created_at", "ready_at", "delivered_at",
                "lines_json", "expanded_json", "cost_rub", "error", "report_json",
                "steps_json", "progress", "steps_n")
        r = c.execute(
            "SELECT %s FROM recall_later WHERE job_id=?" % ",".join(cols), (jid,)
        ).fetchone()
        if not r:
            return None
        d = dict(zip(cols, r))
        for k in ("lines_json", "expanded_json", "report_json", "steps_json"):
            try:
                d[k.replace("_json", "")] = json.loads(d.pop(k) or ("[]" if "steps" in k or "lines" in k or "expanded" in k else "{}"))
            except Exception:
                d[k.replace("_json", "")] = d.pop(k)
        return d
    finally:
        c.close()


def for_recall(uid, cfg):
    """Called on every /memory recall: counts recalls, returns a 'remembered' section for ready jobs past the delay."""
    if not cfg.get("recall_later_enabled", True):
        return ""
    delay = int(cfg.get("recall_later_delay", 3))
    budget = int(cfg.get("recall_later_tokens", 400) or 400)
    with _LOCK:
        c = _conn(uid)
        try:
            n = _n(c) + 1
            c.execute("INSERT OR REPLACE INTO recall_later_state (id, n) VALUES (1, ?)", (n,))
            rows = c.execute(
                "SELECT job_id, query, lines_json, report_json FROM recall_later "
                "WHERE status='done' AND delivered_at IS NULL AND ? - created_n >= ? ORDER BY created_at",
                (n, delay),
            ).fetchall()
            L, used, sent = [], 0, []
            for jid, q, lj, rj in rows:
                try:
                    rep = json.loads(rj or "{}")
                except Exception:
                    rep = {}
                ls = rep.get("lines") or json.loads(lj or "[]")
                summary = (rep.get("summary") or "").strip()
                block = [f"Вспомнилось по запросу «{clip(q, 20)}»:"]
                if summary:
                    block.append(summary)
                block += ([f"- {l.get('text')} [{l.get('id')}]" for l in ls if l.get("text")]
                          or (["- ничего надёжного не нашлось"] if not summary else []))
                srcs = rep.get("sources") or []
                if srcs:
                    block.append("источники: " + ", ".join(
                        f"{s.get('id')} ({s.get('date') or '?'})" for s in srcs[:5]
                    ))
                cost_t = est_tokens("\n".join(block))
                if L and used + cost_t > budget:
                    break
                L += block
                used += cost_t
                sent.append(jid)
            for jid in sent:
                c.execute("UPDATE recall_later SET delivered_at=? WHERE job_id=?", (time.time(), jid))
            c.commit()
        finally:
            c.close()
    return clip("\n".join(L), budget) if L else ""


def jobs(uid, limit=20):
    c = _conn(uid)
    try:
        cols = ("job_id", "query", "status", "created_at", "ready_at", "delivered_at",
                "lines_json", "expanded_json", "cost_rub", "error", "report_json",
                "progress", "steps_n")
        out = []
        for r in c.execute(
            "SELECT %s FROM recall_later ORDER BY created_at DESC LIMIT ?" % ",".join(cols),
            (limit,),
        ):
            d = dict(zip(cols, r))
            for k in ("lines_json", "expanded_json", "report_json"):
                key = k.replace("_json", "")
                try:
                    d[key] = json.loads(d.pop(k) or ("[]" if key != "report" else "{}"))
                except Exception:
                    d[key] = d.pop(k)
            out.append(d)
        return out
    finally:
        c.close()
