import sys, sqlite3, shutil, json
sys.path.insert(0, '/app')
shutil.copy('/data/skv/metadata_store/shared_master.db', '/tmp/court_t.db')
from app import cube_suggest as cs
c = sqlite3.connect('/tmp/court_t.db'); cs.ensure_fix(c)
c.execute("INSERT OR REPLACE INTO cubes_new (cube_id, essence, subject_action_object, rules_markdown, evidence, status, created_by, kind, skill_md, hooks) VALUES ('cube_ct0000000001','e','t','r','test','community','au@t.invalid','moment','','')")
fid = c.execute("INSERT INTO cube_fixes (cube_id,user_id,essence,rules,reason,ts) VALUES ('cube_ct0000000001','filer@t.invalid','e2','r2','fix wording',datetime('now'))").lastrowid
c.execute("INSERT INTO court_queue VALUES ('cube_ct0000000001','fix:1 first',datetime('now'))")
c.execute("UPDATE court_queue SET reason='fix:2 second' WHERE cube_id='cube_ct0000000001'")
r = {}
r["self"] = cs.human_vote(c, fid, 'filer@t.invalid', 'approve', 'looks fine')['ok'] is False
r["noreason"] = cs.human_vote(c, fid, 'j1@t.invalid', 'approve', '')['ok'] is False
a = cs.human_vote(c, fid, 'j1@t.invalid', 'approve', 'clearer wording')
r["one_pending"] = a['decided'] is None
a2 = cs.human_vote(c, fid, 'J1@t.invalid', 'approve', 'again')
r["same_acct_twice_pending"] = a2['decided'] is None
b = cs.human_vote(c, fid, 'j2@t.invalid', 'approve', 'agree, safe')
r["two_approved"] = b['decided'] == 'approved'
v = c.execute("SELECT verdict FROM cube_fixes WHERE id=?", (fid,)).fetchone()[0] or ''
r["reason_stored"] = 'clearer wording' in v or 'again' in v
r["complaints_kept"] = len(cs.complaints(c, 'cube_ct0000000001')) == 2
from app import cubes_v2 as cv
c.execute("INSERT OR REPLACE INTO cubes_new (cube_id, essence, subject_action_object, rules_markdown, evidence, status, created_by, kind) VALUES ('cube_ct0000000002','e2','t2','r','test','community','au@t.invalid','moment')")
cv.add_link(c, 'cube_ct0000000002', 'cube_ct0000000001', 'against', 'x@t.invalid')
r["dispute_appended_when_queued"] = any(x["reason"].startswith("dispute: against cube_ct0000000002") for x in cs.complaints(c, 'cube_ct0000000001'))
c.execute("INSERT OR REPLACE INTO court_queue VALUES ('cube_ct0000000001','fix:9 x',datetime('now'))")
cv.add_link(c, 'cube_ct0000000002', 'cube_ct0000000001', 'against', 'y@t.invalid')
r["queue_routing_kept"] = c.execute("SELECT reason FROM court_queue WHERE cube_id='cube_ct0000000001'").fetchone()[0] == 'fix:9 x'
c.execute("INSERT OR REPLACE INTO cubes_new (cube_id, essence, subject_action_object, rules_markdown, evidence, status, created_by, kind) VALUES ('cube_ct0000000003','e3','t3','r','test','community','mg@t.invalid','moment')")
r["merge_own_superseded"] = cv.merge_part(c, 'cube_ct0000000002', 'cube_ct0000000003', 'mg@t.invalid') == 'merged' and c.execute("SELECT status FROM cubes_new WHERE cube_id='cube_ct0000000003'").fetchone()[0] == 'superseded'
r["merge_foreign_to_court"] = cv.merge_part(c, 'cube_ct0000000002', 'cube_ct0000000001', 'mg@t.invalid') == 'merge_pending' and any(x["reason"].startswith("merge: into") for x in cs.complaints(c, 'cube_ct0000000001'))
r["fresh_not_verified"] = cs.verified_voter(c, 'filer@t.invalid') is False
print(json.dumps(r) if all(r.values()) else "BAD " + json.dumps(r))
