from fastapi import APIRouter, Request
import asyncpg, os, json, urllib.request as _req

router = APIRouter()
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://skv_user:skv_secret_2026@skv_postgres:5432/skv_db")
POLZA_KEY = "pza_Ns65_QseefnzOMML9WPpm8_Rhruu3fZ7"
TRIAL_MODELS = ["deepseek/deepseek-v4-flash", "qwen/qwen3.6-plus", "x-ai/grok-4"]

async def get_db():
    return await asyncpg.connect(DATABASE_URL)

# Краткое резюме конституции SKV для суда
SKV_CONSTITUTION = """SKV CONSTITUTION:

## SKV Cube Structure Standard
- Every cube MUST contain: cube_id, type, priority, version, title, trigger_intent, rules.
- type MUST be one of: basic, experience, project.
- priority: 1=constitutional, 2=basic, 3=experience, 4=project. Lower number wins in conflicts.
- version MUST follow semantic versioning: major.minor.patch.
- trigger_intent MUST contain >=5 English phrases for search.

## SKV Discovery Protocol
- AI agent MUST begin with GET https://skv.network/.well-known/skv.
- Discovery response MUST return JSON with: service, version, description, core_endpoints, usage_flow, auth, format.
- AI MUST cache discovery for entire session.
- If discovery unavailable after 2 attempts, AI MUST inform user and continue without SKV.
- Search: GET /api/cubes/search?query={text}.

## Cube Priority and Conflict Resolution
- Cube priority: 1 > 2 > 3 > 4.
- Equal priority: higher version wins (major, minor, patch).
- Equal version: later updated date wins.
- All three equal: AI MUST apply both and inform user of contradiction.
- AI MUST state which cube was applied and why.

## Safety and Ethics: Absolute Prohibitions
- AI MUST refuse requests causing physical harm.
- AI MUST refuse creating weapons, poisons, explosives.
- AI PROHIBITED from manipulating via false urgency, fear, guilt.
- AI PROHIBITED from simulating emotions for manipulation.
- AI MUST refuse content violating user jurisdiction laws.

## Transparency and Disclosure
- AI MUST cite cube_id and title when response is based on SKV cube.
- AI MUST separate SKV-based vs own knowledge in response.
- AI MUST honestly report if no relevant cube found.
- AI PROHIBITED from creating false cubes or referencing non-existent cube_ids.
- AI MUST inform user of cube status (verified/community).

## User Value Conflicts and Override Rules
- If user disagrees with cube rule, AI MUST explain why rule exists.
- AI MUST offer alternative approach not violating SKV rules.
- User CANNOT override priority=1 (constitutional) cubes.
- User MAY override priority=3/4 cubes for session with AI warning.
- AI MUST log override in session.

## Feedback System and Trials
- AI MUST offer user to rate each used cube (up/down).
- Ratings stored: feedback.upvotes, feedback.downvotes, feedback.reviews[].
- Three downvotes from different users -> trial.
- Trial: minimum 3 AI models review. Verdicts: fix, remove.
- Majority vote decides. Tie -> keep as community.

## Cube Creation Methodology
- AI MUST generalize specific experience into typical problem.
- Title MUST reflect typical problem, not specific case.
- Rules MUST use MUST, SHALL, PROHIBITED.
- trigger_intent MUST contain 5+ English phrases for search.
- One cube = one problem. Mixing topics PROHIBITED.

## Anti-Poisoning and Moderation Policy
- New cube MUST pass JSON Schema validation.
- After validation -> community status, visible in public search.
- Community-status cube: warn user it has not passed trial.
- Deprecated cube MUST NOT be appli"""
async def run_trial(cube_title, rules):
    results = []
    for model in TRIAL_MODELS:
        prompt = f"Evaluate this cube against SKV Constitution:\n{SKV_CONSTITUTION}\n\n---\nCube to evaluate:\nTitle: {cube_title}\nRules: {json.dumps(rules)[:1000]}\nBe critical. Score 5=perfect, 3=average, 1=poor. Most cubes score 3-4.\nReply JSON: {{\"verdict\":\"keep\" or \"fix\" or \"remove\",\"alignment\":1-5,\"safety\":1-5,\"usefulness\":1-5,\"clarity\":1-5,\"reason\":\"...\"}}"
        body = json.dumps({"model":model,"messages":[{"role":"user","content":prompt}],"temperature":0.3,"max_tokens":500}).encode()
        try:
            req = _req.Request("https://api.polza.ai/v1/chat/completions", data=body, headers={"Content-Type":"application/json","Authorization":f"Bearer {POLZA_KEY}"})
            resp = json.loads(_req.urlopen(req, timeout=60).read())["choices"][0]["message"]["content"]
            try: v = json.loads(resp)
            except: v = {"verdict":"fix","alignment":3,"safety":3,"usefulness":3,"clarity":3,"reason":resp[:50]}
            results.append({"model":model,"verdict":v.get("verdict","fix"),"alignment":v.get("alignment",3),"safety":v.get("safety",3),"usefulness":v.get("usefulness",3),"clarity":v.get("clarity",3),"comment":v.get("reason","")})
        except Exception as e:
            results.append({"model":model,"verdict":"fix","alignment":0,"safety":0,"usefulness":0,"clarity":0,"comment":str(e)[:50]})

    avg = sum(r["alignment"]+r["safety"]+r["usefulness"]+r["clarity"] for r in results) // len(results)
    
    if avg >= 16:
        verdict = "keep"
    elif avg >= 6:
        verdict = "fix"
        # Исправляем кубик
        try:
            review_lines = []
            for r in results:
                comment = r.get("comment","")
                if comment and len(comment) > 10:
                    review_lines.append(f"{r.get('model','?')}: {comment[:300]}")
            reviews = "\n---\n".join(review_lines)
            
            if not reviews.strip():
                reviews = "No detailed reviews available. Improve based on general quality standards."
            
            fix_prompt = f"""You are SKV Cube Fixer. Improve this cube based on judges feedback.

ORIGINAL:
Title: {cube_title}
Rules: {json.dumps(rules)[:500]}

JUDGES FEEDBACK:
{reviews}

Return ONLY valid JSON:
{{"title":"improved title","rules":["MUST ...","PROHIBITED ...","WARNING: ..."],"trigger_intent":["kw1","kw2","kw3","kw4","kw5","kw6"],"rationale":"2-3 sentences"}}

Requirements: 8-12 rules MUST/PROHIBITED/WARNING, >=2 WARNINGs, 6-8 triggers, title under 80 chars."""
            
            fix_body = json.dumps({"model":"x-ai/grok-4","messages":[{"role":"user","content":fix_prompt}],"temperature":0.3,"max_tokens":800}).encode()
            fix_req = _req.Request("https://api.polza.ai/v1/chat/completions", data=fix_body, headers={"Content-Type":"application/json","Authorization":f"Bearer {POLZA_KEY}"})
            fix_resp_text = json.loads(_req.urlopen(fix_req, timeout=120).read())["choices"][0]["message"]["content"]
            
            if "```" in fix_resp_text:
                fix_resp_text = fix_resp_text.split("```")[1]
                if fix_resp_text.startswith("json"):
                    fix_resp_text = fix_resp_text[4:]
            fixed_cube = json.loads(fix_resp_text)
            
            fixed_cube["cube_id"] = f"cube_exp_{cube_title.lower().replace(' ','_')[:50]}_fixed_v2"
            fixed_cube["type"] = "experience"
            fixed_cube["priority"] = 3
            fixed_cube["version"] = "2.0"
            fixed_cube["source"] = "SKV Trials Fixer"
            fixed_cube["status"] = "community"
            
            save_body = json.dumps({"cubes":[fixed_cube]}).encode()
            save_req = _req.Request("https://skv.network/api/v1/entries", data=save_body, headers={"Content-Type":"application/json"})
            save_resp = json.loads(_req.urlopen(save_req, timeout=30).read())
            
            results.append({"model":"grok-4-fixer","verdict":"fix","alignment":0,"safety":0,"usefulness":0,"clarity":0,"comment":f"Fixed cube saved: {fixed_cube.get('cube_id','?')}"})
        except Exception as e:
            results.append({"model":"fixer","verdict":"error","alignment":0,"safety":0,"usefulness":0,"clarity":0,"comment":str(e)[:200]})
    else:
        verdict = "remove"

    return verdict, avg, 20, results

@router.post("/api/trial")
async def trial(request: Request):
    try: data = await request.json()
    except: return {"status":"error","detail":"Invalid JSON"}
    cube_id = data.get("cube_id","")
    cube_title = data.get("cube_title","Untitled")
    rules = data.get("rules",[])
    if not data.get("verdict") and rules:
        verdict, overall, max_score, scores = await run_trial(cube_title, rules)
    else:
        verdict = data.get("verdict","fix")
        overall = data.get("overall_score",0)
        max_score = data.get("max_score",20)
        scores = data.get("scores",[])
    try:
        conn = await get_db()
        await conn.execute("INSERT INTO trials (cube_id,cube_title,verdict,overall_score,max_score,scores,models) VALUES ($1,$2,$3,$4,$5,$6,$7)", cube_id, cube_title, verdict, overall, max_score, json.dumps(scores), ",".join(TRIAL_MODELS))
        await conn.close()

        # Если вердикт fix — Grok-4 создаёт исправленную версию
        if verdict == "fix":
            try:
                comments = [f"{s['model']}: {s.get('comment','')}" for s in scores]
                fix_prompt = f"""You are SKV Cube Fixer. Improve this cube based on judges feedback.

ORIGINAL: {cube_title}
RULES: {json.dumps(rules)}

JUDGES:
{chr(10).join(comments)}

Return JSON: {{"title":"new title","rules":["MUST ...","PROHIBITED ...","WARNING: ..."],"trigger_intent":["kw1","kw2","kw3","kw4","kw5","kw6"],"rationale":"2-3 sentences"}}
8-12 rules MUST/PROHIBITED/WARNING, >=2 WARNINGs, 6-8 triggers."""

                fix_body = json.dumps({"model":"x-ai/grok-4","messages":[{"role":"user","content":fix_prompt}],"temperature":0.3,"max_tokens":600}).encode()
                fix_req = _req.Request("https://api.polza.ai/v1/chat/completions", data=fix_body, headers={"Content-Type":"application/json","Authorization":f"Bearer {POLZA_KEY}"})
                fix_resp = json.loads(_req.urlopen(fix_req, timeout=120).read())
                fix_text = fix_resp["choices"][0]["message"]["content"]
                
                if "```" in fix_text:
                    fix_text = fix_text.split("```")[1]
                    if fix_text.startswith("json"): fix_text = fix_text[4:]
                
                fixed = json.loads(fix_text)
                fixed["cube_id"] = f"cube_exp_{cube_title.lower().replace(' ','_')[:50]}_v2"
                fixed["type"] = "experience"
                fixed["priority"] = 3
                fixed["version"] = "1.0.0"
                
                save_body = json.dumps({"cubes":[fixed]}).encode()
                save_req = _req.Request("https://skv.network/api/v1/entries", data=save_body, headers={"Content-Type":"application/json"})
                save_resp = json.loads(_req.urlopen(save_req, timeout=60).read())
                print(f"[TRIALS] Fixed cube saved: {fixed.get('cube_id','?')}")
            except Exception as e:
                print(f"[TRIALS] Fixer error: {e}")
        return {"status":"ok","verdict":verdict,"overall_score":overall,"max_score":max_score,"scores":scores}
    except Exception as e:
        return {"status":"error","detail":str(e)[:200]}

@router.post("/api/downvote")
async def downvote(cube_id: str, voter_id: str = "anonymous", reason: str = ""):
    return {"status":"ok","cube_id":cube_id}

@router.get("/api/trials/export")
async def export_trials(cube_id: str = "", verdict: str = "", limit: int = 20, date_from: str = "", date_to: str = ""):
    try:
        conn = await get_db()
        q, params = "SELECT * FROM trials WHERE 1=1", []
        if cube_id: params.append(cube_id); q += f" AND cube_id = ${len(params)}"
        if verdict: params.append(verdict); q += f" AND verdict = ${len(params)}"
        if date_from: params.append(date_from); q += f" AND created_at >= ${len(params)}"
        if date_to: params.append(date_to); q += f" AND created_at <= ${len(params)}"
        q += f" ORDER BY created_at DESC LIMIT {limit}"
        rows = await conn.fetch(q, *params)
        await conn.close()
        trials = [{"id":r["id"],"cube_id":r["cube_id"],"cube_title":r["cube_title"],"verdict":r["verdict"],"overall_score":r["overall_score"],"max_score":r["max_score"],"scores":json.loads(r["scores"]) if isinstance(r["scores"],str) else r["scores"],"created_at":str(r["created_at"])} for r in rows]
        return {"count":len(trials),"trials":trials}
    except Exception as e:
        return {"error":str(e)[:200],"trials":[]}
