"""Delayed recall ('вспомнилось позже' / deep_search).

POST /memory/recall_later {user_id, query} queues a background job:
  cheap LLM agent on the server runs 5–30 lens/search/focus steps,
  writes a report WITH sources (ids, dates, notes), stores it,
  delivers once later in /memory as 'remembered' (after recall_later_delay),
  and is always available via GET /memory/recall_later/{job_id}.

Trigger: agent requests deep_search, or fast /search returns no_confident_match.

Config: recall_later_enabled, recall_later_tokens (400), recall_later_delay (3),
recall_later_model (falls back to llm_model), recall_later_max_cost_rub (3.0),
recall_later_max_steps (15, clamped 5..30), recall_later_min_steps (5),
recall_later_format ('substrate' default: report = ranked evidence events with verbatim
text, ids, dates, neighbour turns, why/missing notes, no answer; 'answer' = legacy _run_answer),
recall_later_plan / recall_later_q2s_seed / recall_later_agent_steps (6) / recall_later_min_agent_steps (1) /
recall_later_evidence_k (8) / recall_later_context_radius (1) for substrate mode,
recall_later_reasoning ('retry' default: on empty LLM content retry once with
reasoning disabled; 'off': always disable reasoning; 'legacy': no handling).
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
    mode = str(cfg.get("recall_later_reasoning", "retry") or "retry").lower()
    total = 0.0
    for attempt in (0, 1):
        body = {"model": model, "messages": messages, "temperature": 0.1, "max_tokens": max_tokens}
        if mode == "off" or attempt == 1:
            body["reasoning"] = {"enabled": False}
        req = urllib.request.Request(
            L.URL,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + os.environ.get("POLZA_KEY", "")},
        )
        with urllib.request.urlopen(req, timeout=90) as r:
            d = json.loads(r.read())
        u = d.get("usage") or {}
        cost = u.get("cost_rub", d.get("cost_rub", u.get("cost", d.get("cost")))) or 0
        total += float(cost or 0)
        L._log({"ts": time.time(), "job": "recall_later", "model": model,
                "prompt": u.get("prompt_tokens", 0), "completion": u.get("completion_tokens", 0),
                "cost_rub": cost, "attempt": attempt})
        ch = d["choices"][0]
        content = (ch.get("message") or {}).get("content") or ""
        # Reasoning models can burn all max_tokens on hidden reasoning -> empty content.
        # mode "retry" (default): repeat once with reasoning disabled; "legacy": old behaviour.
        if content.strip() or mode != "retry" or attempt == 1:
            return content, total, model
    return content, total, model


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


def _run_answer(uid, jid):
    """Legacy answer-style report (recall_later_format=answer)."""
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
                if rep.get("format") == "substrate":
                    block = _substrate_block(q, rep, budget - used)
                    cost_t = est_tokens("\n".join(block))
                    if L and used + cost_t > budget:
                        break
                    L += block
                    used += cost_t
                    sent.append(jid)
                    continue
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


# ---------------- 2026-11-02 SUBSTRATE mode ----------------
# Deferred search returns evidence for the calling agent, never an answer.
# Flag recall_later_format: "substrate" (default) | "answer" (legacy _run_answer).
# Sub-flags: recall_later_plan (LLM query plan: statement forms + EN/native terms, default true),
# recall_later_q2s_seed (q2s/search_v2 pipeline as a seed, default true),
# recall_later_agent_steps (max agent LLM actions after seeds, default 6),
# recall_later_min_agent_steps (default 1), recall_later_evidence_k (8), recall_later_context_radius (1).

_SUB_SYSTEM = (
    "You collect EVIDENCE from a person's memory for another agent who will answer the question. "
    "You never answer the question yourself and never state conclusions.\n"
    "Reply with exactly ONE JSON object, no markdown.\n"
    "Actions:\n"
    '{"action":"search","query":"short query (any language; try English and the question language, names, synonyms, '
    'a declarative sentence that could appear in the conversation)"}\n'
    '{"action":"focus","event_id":"<id from observations>","query":"why"}  (neighbouring turns of an event)\n'
    '{"action":"more","query":"same query","cursor":N}\n'
    '{"action":"done","evidence":[{"id":"<id from observations>","why":"what this event contains that relates to the question, <=100 chars; describe, do not compute or state the answer"}],'
    '"missing":"which information the question needs that no observation shows, <=200 chars"}\n'
    "Rules: ids only from observations; evidence ordered best first, up to 8, include indirect evidence "
    "(dates, events around it, people involved); if nothing is relevant, evidence=[] and say what is missing. "
    "Search with different wordings before done. NEVER write the answer or a conclusion anywhere (no resolved relative dates, "
    "no 'so/therefore/indicating', no counts or totals): only point at events; the other agent reasons."
)

_PLAN_SYSTEM = (
    "You turn a memory question into search material. Reply with ONE JSON object only: "
    '{"forms":["2-4 short declarative sentences in ENGLISH that could literally appear in the past conversation '
    'and contain the answer topic (no invented facts; names in their usual Latin/English spelling)"],'
    '"native":["1-2 such sentences in the question\'s own language if it is not English"],'
    '"terms":["4-8 keywords: names, nouns, verbs, both English and original language"]}'
)

_LANG_TXT = {
    "ru": ("Материал для ответа по запросу «{q}»: {n} событий (дословный текст, даты, соседние реплики). "
           "Это не ответ: ответ формулирует агент сам, со ссылками [ev:id].",
           "Модель недоступна: события упорядочены только поиском, без отбора.",
           "Ничего похожего не найдено."),
    "es": ("Material para responder «{q}»: {n} eventos (texto literal, fechas, turnos vecinos). "
           "No es una respuesta: el agente responde citando [ev:id].",
           "Modelo no disponible: eventos ordenados solo por la búsqueda, sin selección.",
           "No se encontró nada parecido."),
    "de": ("Material zur Beantwortung von «{q}»: {n} Ereignisse (wörtlicher Text, Daten, Nachbarbeiträge). "
           "Keine Antwort: der Agent antwortet selbst mit [ev:id].",
           "Modell nicht verfügbar: Ereignisse nur nach Suche sortiert, ohne Auswahl.",
           "Nichts Ähnliches gefunden."),
    "en": ("Evidence for «{q}»: {n} events (verbatim text, dates, neighbouring turns). "
           "Not an answer: answer it yourself from this, citing [ev:id].",
           "Model unavailable: events ranked by search only, not selected.",
           "Nothing similar found."),
}


def _lang(q):
    q = q or ""
    if re.search(r"[А-Яа-яЁё]", q):
        return "ru"
    ql = q.lower()
    if re.search(r"[¿¡ñ]", ql) or re.match(r"\s*(qu[ée]|c[oó]mo|cu[aá]ndo|d[oó]nde|por qu[ée]|qui[eé]n|cu[aá]l)\b", ql):
        return "es"
    de_w = r"\b(der|die|das|den|dem|hat|haben|ist|sind|und|nicht|sie|er|ihr|ihre|sein|seine|gemacht|wann|welche\w*|warum|wie)\b"
    if (re.search(r"[äöüß]", ql) or len(re.findall(de_w, ql)) >= 2
            or re.match(r"\s*(was|wann|wo|wer|wie|warum|welche\w*)\s+(hat|ist|sind|haben|war|waren|wurde|macht|mag|kann|will)\b", ql)):
        return "de"
    return "en"


def _cfg_bool(cfg, key, default=True):
    v = cfg.get(key, default)
    return str(v).lower() not in ("0", "false", "off", "no", "none") if v is not None else default


def _plan(q):
    """One cheap LLM call -> statement forms (EN + native) and terms. ({} on failure)."""
    try:
        txt, k, _m = _llm([{"role": "system", "content": _PLAN_SYSTEM}, {"role": "user", "content": q[:400]}], 400)
        d = _json(txt)
        out = {}
        for key, n in (("forms", 4), ("native", 2), ("terms", 8)):
            v = d.get(key) or []
            out[key] = [mask_text(str(x))[:200] for x in v if isinstance(x, (str, int))][:n] if isinstance(v, list) else []
        return out, k
    except Exception as e:
        print(f"[recall_later] plan skipped: {e}", flush=True)
        return {}, 0.0


def _q2s_list(uid, q, forms=None, k=20):
    """[(eid, score)] from the q2s/search_v2 pipeline (agent forms when given), hybrid fallback."""
    try:
        from app import q2s
        r = q2s.search(uid, q, top_k=k, search_as=forms or None)
        if r:
            return [(e, s) for e, s in r if str(e).startswith(f"{uid}::")]
    except Exception as e:
        print(f"[recall_later] q2s seed skipped: {type(e).__name__}", flush=True)
    try:
        from app import search_v2 as _v2
        r, _ = _v2.hybrid(uid, q, top_k=k)
        return [(e, s) for e, s in r if str(e).startswith(f"{uid}::")]
    except Exception:
        return []


def _lens_ids(res):
    out = []
    for cl in (res or {}).get("clusters") or []:
        center = cl.get("center") or cl.get("event") or {}
        e = center.get("event_id") or cl.get("event_id")
        if e:
            out.append(e)
    return out


def _preview_rows(uid, ids, cap=160):
    from app.memory_v2 import _event_rows
    rows = _event_rows(uid, ids)
    lines = []
    for e in ids:
        r = rows.get(e)
        if r:
            lines.append(f"id={e} {str(r['date'])[:10]} :: {mask_text(clip(r['text'] or '', cap // 4, headtail=True))}")
    return lines


class _Pool:
    """Candidate events: weighted RRF over all search lists, provenance kept."""

    def __init__(self):
        self.score, self.src = {}, {}

    def add(self, ids, w, tag, k=60):
        for r, e in enumerate(ids):
            self.score[e] = self.score.get(e, 0.0) + w / (k + r + 1)
            self.src.setdefault(e, [])
            if tag not in self.src[e]:
                self.src[e].append(tag)

    def ranked(self):
        return [e for e, _ in sorted(self.score.items(), key=lambda x: -x[1])]


def _substrate(uid, q, picks, pool, missing, lang, model_ok, expanded, cfg):
    """Assemble ranked evidence: agent picks first, then pool by score; verbatim text + neighbours from the DB."""
    import sqlite3
    from app.memory_v2 import db_path, strip_critical
    K = max(1, min(15, int(cfg.get("recall_later_evidence_k", 8) or 8)))
    rad = max(0, min(3, int(cfg.get("recall_later_context_radius", 1) or 0)))
    order, why = [], {}
    for p in picks:
        if p["id"] not in order:
            order.append(p["id"]); why[p["id"]] = p.get("why") or ""
    for e in pool.ranked():
        if len(order) >= K:
            break
        if e not in order:
            order.append(e)
    order = order[:K]
    ev = []
    conn = sqlite3.connect(f"file:{db_path(uid)}?mode=ro", uri=True, timeout=10)
    try:
        for i, e in enumerate(order):
            r = conn.execute("SELECT rowid, time_str, raw_dialogue, essence FROM event_metadata WHERE event_id=?", (e,)).fetchone()
            if not r:
                continue
            raw = r[2] or r[3] or ""
            if raw.startswith("[archived]"):
                try:
                    from app.archive_store import text_of
                    ar = conn.execute("SELECT raw_dialogue, body_z FROM event_archive WHERE event_id=?", (e,)).fetchone()
                    raw = (text_of(ar[0], ar[1]) if ar else "") or raw
                except Exception:
                    pass
            ctx = []
            if rad:
                b = conn.execute("SELECT event_id, time_str, raw_dialogue FROM event_metadata WHERE rowid < ? ORDER BY rowid DESC LIMIT ?", (r[0], rad)).fetchall()
                a = conn.execute("SELECT event_id, time_str, raw_dialogue FROM event_metadata WHERE rowid > ? ORDER BY rowid ASC LIMIT ?", (r[0], rad)).fetchall()
                for side, rows in (("before", list(reversed(b))), ("after", a)):
                    for x in rows:
                        ctx.append({"side": side, "ev": x[0], "date": norm_date(x[1] or "")[:16],
                                    "text": mask_text(clip(strip_critical(x[2] or "") or (x[2] or ""), 60, headtail=True))})
            picked = e in why
            ev.append({
                "rank": len(ev) + 1, "ev": e, "date": norm_date(r[1] or "")[:16],
                "text": mask_text(clip(strip_critical(raw) or raw, 180, headtail=True)),
                "context": ctx,
                "why": mask_text(why.get(e) or "")[:160] if picked else "search rank (%s), not checked by the agent" % "+".join(pool.src.get(e, ["search"])[:3]),
                "selected": picked,
            })
    finally:
        conn.close()
    T = _LANG_TXT.get(lang, _LANG_TXT["en"])
    miss = mask_text(str(missing or ""))[:300]
    if not model_ok:
        miss = (T[1] + (" " + miss if miss else "")).strip()
    if not ev:
        miss = (T[2] + (" " + miss if miss else "")).strip()
    return {
        "format": "substrate",
        "found": any(x["selected"] for x in ev),
        "evidence_n": len(ev),
        "summary": T[0].format(q=clip(q, 60), n=len(ev)),
        "evidence": ev,
        "missing": miss,
        "queries": expanded[:12],
        # compat for old readers: sources = evidence ids; no answer lines
        "sources": [{"id": x["ev"], "date": x["date"][:10], "note": x["why"][:80]} for x in ev],
        "lines": [],
    }


def _run_substrate(uid, jid):
    from app import inflight
    cfg = config()
    cap = float(cfg.get("recall_later_max_cost_rub", 3.0))
    max_agent = max(0, min(20, int(cfg.get("recall_later_agent_steps", 6) or 0)))
    min_agent = max(0, min(max_agent, int(cfg.get("recall_later_min_agent_steps", 1) or 0)))
    cost, steps_log, observations, known_ids = 0.0, [], [], set()
    pool, picks, missing, err, model_ok = _Pool(), [], "", None, True
    c = _conn(uid)
    q = c.execute("SELECT query FROM recall_later WHERE job_id=?", (jid,)).fetchone()[0]
    c.execute("UPDATE recall_later SET status='running', progress=? WHERE job_id=?", ("running", jid))
    c.commit(); c.close()
    expanded = [q]
    lang = _lang(q)
    agent_n = 0
    report = {}

    def _search(sq, tag, w, forms=None, cursor=0):
        """q2s list + lens around it (neighbours). Returns observation text."""
        nonlocal known_ids
        ql = _q2s_list(uid, sq, forms) if _cfg_bool(cfg, "recall_later_q2s_seed") else []
        pool.add([e for e, _ in ql[:20]], w, tag + ":q2s")
        try:
            raw = [{"event_id": e} for e, _ in ql] if ql else None
            res = lens_mod.lens(uid, sq, raw_results=raw, budget=int(config().get("budgets", {}).get("lens", 1500) or 1500),
                                radius=2, offset=int(cursor or 0))
        except Exception as e:
            res = {"error": str(e)[:100]}
        pool.add(_lens_ids(res), w * 0.8, tag + ":lens")
        obs = f"search({sq!r}):\n" + "\n".join(_preview_rows(uid, [e for e, _ in ql[:6]])) + "\n" + _fmt_lens(res)
        known_ids |= _collect_ids(obs) | {e for e, _ in ql[:20]}
        return obs

    from app import memory_v2_lens as lens_mod
    with inflight.track("recall_later"):
        try:
            # seeds (do not count against agent steps)
            plan = {}
            if _cfg_bool(cfg, "recall_later_plan"):
                plan, k = _plan(q)
                cost += k
                steps_log.append({"action": "plan", "seed": True, "ok": bool(plan)})
            forms = (plan.get("forms") or []) + (plan.get("native") or [])
            _set_progress(uid, jid, "seed search", steps_n=0)
            observations.append(_search(q, "q", 1.0))
            steps_log.append({"action": "search", "query": q, "seed": True})
            if forms:
                observations.append(_search(q, "forms", 1.0, forms=forms) .replace(f"search({q!r})", f"search(forms={forms[:2]!r})", 1))
                steps_log.append({"action": "search_forms", "forms": forms, "seed": True})
                expanded += forms
            terms = " ".join(plan.get("terms") or [])
            if terms:
                observations.append(_search(terms, "terms", 0.7))
                steps_log.append({"action": "search", "query": terms, "seed": True})
                expanded.append(terms)
            try:   # archive: old period or nothing at all
                from app import archive_recall as _ar
                if not pool.score or _ar.is_old(q):
                    ah = _ar.search(uid, q, limit=6)
                    if ah:
                        pool.add([a["event_id"] for a in ah], 0.6, "archive")
                        observations.append("archive:\n" + "\n".join("id=%s [%s] (archived) %s" % (a["event_id"], a["time_str"], a["snippet"]) for a in ah))
                        known_ids |= {a["event_id"] for a in ah}
            except Exception:
                pass

            # agent loop: only LLM actions count (steps_n = agent steps)
            while agent_n < max_agent and cost < cap:
                obs_block = "\n---\n".join(_clip_obs(observations))
                user = (f"Question: {q}\nAgent step {agent_n+1}/{max_agent}.\n"
                        f"Observations:\n{obs_block}\n\nNext action JSON.")
                if agent_n < min_agent:
                    user += " Do at least one more search/focus before done."
                try:
                    txt, k, _m = _llm([{"role": "system", "content": _SUB_SYSTEM}, {"role": "user", "content": user}], 900)
                    cost += k
                except Exception as e:
                    err, model_ok = f"llm:{e}"[:200], False
                    break
                agent_n += 1
                act = _json(txt)
                action = (act.get("action") or "").lower().strip()
                if action not in ("search", "focus", "more", "done") and "evidence" in act:
                    action = "done"
                if action == "search":
                    sq = mask_text(str(act.get("query") or q))[:200] or q
                    if sq not in expanded:
                        expanded.append(sq)
                    observations.append(_search(sq, "agent", 0.8))
                    steps_log.append({"action": "search", "query": sq})
                elif action == "more":
                    sq = mask_text(str(act.get("query") or q))[:200] or q
                    cur = int(act.get("cursor") or 0)
                    observations.append(_search(sq, "agent", 0.5, cursor=cur))
                    steps_log.append({"action": "more", "query": sq, "cursor": cur})
                elif action == "focus":
                    fe = str(act.get("event_id") or "").strip()
                    if "::" not in fe:
                        observations.append("focus ERROR: need an event id from observations")
                        steps_log.append({"action": "focus", "error": "missing id"})
                    else:
                        try:
                            res = _lens_search(uid, str(act.get("query") or q)[:200], focus_event_id=fe)
                            obs = f"focus({fe}):\n{_fmt_lens(res)}"
                            known_ids |= _collect_ids(obs)
                            pool.add([fe], 0.5, "focus")
                            steps_log.append({"action": "focus", "event_id": fe})
                        except Exception as e:
                            obs = f"focus ERROR: {e}"
                            steps_log.append({"action": "focus", "event_id": fe, "error": str(e)[:100]})
                        observations.append(obs)
                elif action == "done":
                    if agent_n <= min_agent and agent_n < max_agent:
                        observations.append("SYSTEM: too early for done; search with another wording or focus first.")
                        steps_log.append({"action": "done_rejected_early"})
                        continue
                    for p in (act.get("evidence") or [])[:15]:
                        if isinstance(p, dict) and str(p.get("id") or "") in known_ids:
                            picks.append({"id": str(p["id"]), "why": str(p.get("why") or "")})
                    missing = str(act.get("missing") or "")
                    steps_log.append({"action": "done", "picked": len(picks)})
                    break
                else:
                    steps_log.append({"action": "parse_fail", "raw": mask_text(str(txt)[:200])})
                    observations.append("PARSE_FAIL: reply with exactly one JSON action.")
                _set_progress(uid, jid, f"{action or 'parse_fail'}:{agent_n}", steps_n=agent_n)
            else:
                # out of agent steps/budget without done: one short selection call
                if model_ok and cost < cap and not picks:
                    try:
                        obs_block = "\n---\n".join(_clip_obs(observations, 2800))
                        txt, k, _m = _llm([{"role": "system", "content": _SUB_SYSTEM}, {"role": "user", "content": (
                            f"Question: {q}\nStep limit reached: reply action=done now.\nObservations:\n{obs_block}")}], 700)
                        cost += k
                        act = _json(txt)
                        for p in (act.get("evidence") or [])[:15]:
                            if isinstance(p, dict) and str(p.get("id") or "") in known_ids:
                                picks.append({"id": str(p["id"]), "why": str(p.get("why") or "")})
                        missing = str(act.get("missing") or "")
                        steps_log.append({"action": "done_forced", "picked": len(picks)})
                    except Exception as e:
                        err, model_ok = (err or "") + f"|final:{e}"[:180], False
            if not picks and not missing and not any(s.get("action") in ("done", "done_forced") for s in steps_log):
                model_ok = False   # no agent selection at all -> search-ranked fallback, said so in 'missing'
            report = _substrate(uid, q, picks, pool, missing, lang, model_ok, expanded, cfg)
            report["seed_steps"] = sum(1 for s in steps_log if s.get("seed"))
            report["agent_steps"] = agent_n
            report["cost_rub"] = round(cost, 4)
            report["expanded"] = expanded
        except Exception as e:
            err = str(e)[:200]
            print(f"[recall_later] {jid} failed: {e}", flush=True)
            try:
                report = _substrate(uid, q, picks, pool, missing, lang, False, expanded, cfg)
            except Exception:
                report = {"format": "substrate", "found": False, "evidence": [], "summary": _LANG_TXT.get(lang, _LANG_TXT["en"])[2],
                          "missing": f"error: {err}", "sources": [], "lines": []}

    c = _conn(uid)
    c.execute(
        "UPDATE recall_later SET status=?, ready_at=?, lines_json=?, expanded_json=?, cost_rub=?, "
        "error=?, report_json=?, steps_json=?, progress=?, steps_n=? WHERE job_id=?",
        ("done" if report.get("summary") else "error", time.time(), "[]", json.dumps(expanded, ensure_ascii=False),
         round(cost, 4), err, json.dumps(report, ensure_ascii=False), json.dumps(steps_log, ensure_ascii=False),
         "done" if not err else f"done (soft error: {err[:60]})", agent_n, jid))
    c.commit()
    c.close()


def run(uid, jid):
    fmt = str(config().get("recall_later_format", "substrate") or "substrate").lower()
    if fmt == "answer":
        return _run_answer(uid, jid)
    return _run_substrate(uid, jid)


def _substrate_block(q, rep, budget_left):
    """Compact 'remembered' block for /memory delivery: evidence, not an answer."""
    T = _LANG_TXT.get(_lang(q), _LANG_TXT["en"])
    block = [f"Deferred search «{clip(q, 30)}» - evidence, not an answer:"]
    for x in (rep.get("evidence") or [])[:4]:
        block.append(f"- [ev:{x.get('ev')}] {x.get('date','')[:10]}: {clip(x.get('text') or '', 30)}")
    if not rep.get("evidence"):
        block.append("- " + T[2])
    if rep.get("missing"):
        block.append("missing: " + clip(rep["missing"], 30))
    return block
