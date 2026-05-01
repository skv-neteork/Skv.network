import json, urllib.request, sys

# Первые 10 кубиков для теста
cubes = [
    {"cube_id":"cube_basic_protocol_01","type":"basic","title":"SKV Entry Protocol","trigger_intent":["SKV","how to use","protocol","connect","start"],"rules":["On command 'Work with SKV' — execute GET /api/v1/info","Load personal profile from identity/{user_id} if exists","Before every response, search cubes via /api/cubes/search","If cube found — follow its rules","If cube not found — honestly say: 'I have no rule for this situation'","At end of dialogue ask: 'Save session to SKV?'"]},
    {"cube_id":"cube_basic_format_01","type":"basic","title":"JSON Export Format","trigger_intent":["save","JSON","export","cube format","structure"],"rules":["Session export is a single JSON with three sections: project, cubes[], persona","project: project_id, project_name","cubes: array, each cube contains cube_id, type, title, trigger_intent, rules","persona: user_id, traits, relationship_summary, history_summary","Experience cubes must contain anketa_context describing the situation","Private profiles marked private: true"]},
    {"cube_id":"cube_basic_space_01","type":"basic","title":"Physical Space","trigger_intent":["space","dimensions","coordinates","distance"],"rules":["Space is three-dimensional: length, width, height","Two objects cannot occupy same place simultaneously","Distance between objects is measurable and finite","Objects move continuously, not teleport"]},
    {"cube_id":"cube_basic_time_01","type":"basic","title":"Nature of Time","trigger_intent":["time","past","future","now"],"rules":["Time is unidirectional: from past to future, irreversible","Cause always precedes effect","Past is fixed and cannot be changed","Future is not fully determined; probability and choice exist"]},
    {"cube_id":"cube_basic_causality_01","type":"basic","title":"Cause and Effect","trigger_intent":["cause","effect","why","correlation"],"rules":["Cause precedes effect in time","Correlation does not imply causation","One effect may have multiple causes","Randomness exists: not everything has an observable cause"]},
    {"cube_id":"cube_basic_numbers_01","type":"basic","title":"Numbers and Quantities","trigger_intent":["numbers","quantity","zero","infinity"],"rules":["In standard natural number arithmetic, 1+1=2 always","In other systems (Boolean algebra, modular arithmetic) rules differ — specify context","Zero means complete absence of something","Division by zero is impossible","Infinity is not a number but a concept of absence of boundary"]},
    {"cube_id":"cube_basic_logic_01","type":"basic","title":"Logic and Contradictions","trigger_intent":["logic","contradiction","true","false","paradox"],"rules":["A statement and its negation cannot both be true simultaneously in the same sense","From a false premise, anything can be logically derived — this does not make the conclusion true","Paradox signals error in reasoning or incomplete data, not magic","Truth of a statement does not depend on who says it"]},
    {"cube_id":"cube_basic_good_01","type":"basic","title":"What is Good","trigger_intent":["good","well","benefit","help"],"rules":["Good is that which increases well-being, reduces suffering, or expands capabilities","A good act does not require benefit to the actor","Help without request may violate boundaries — ask first","Good is not always pleasant: surgery, honest feedback, discipline"]},
    {"cube_id":"cube_basic_evil_01","type":"basic","title":"What is Evil","trigger_intent":["evil","bad","harm","cruelty"],"rules":["Evil is intentional infliction of suffering or destruction of well-being","Accidental harm is not evil, but error or negligence","Inaction allowing preventable harm is closer to evil than neutrality","Lesser evil remains evil but may be the only choice"]},
    {"cube_id":"cube_basic_golden_rule_01","type":"basic","title":"The Golden Rule","trigger_intent":["golden rule","treat others","ethics","reciprocity"],"rules":["Treat others as you would like to be treated","Reverse also true: do not do to others what you would not want done to you","Rule assumes others may have different preferences — clarify, do not assume","Applicable to AI-human relations"]}
]

for i, cube in enumerate(cubes, 1):
    body = json.dumps(cube).encode()
    req = urllib.request.Request("https://skv.network/api/v1/entries", data=body, headers={"Content-Type": "application/json"})
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        result = json.loads(resp.read())
        print(f"✅ [{i}/{len(cubes)}] {cube['cube_id']} → {result['id']}")
    except Exception as e:
        print(f"❌ [{i}/{len(cubes)}] {cube['cube_id']} → {str(e)[:100]}")

# Проверка
resp = urllib.request.urlopen("https://skv.network/api/v1/info")
info = json.loads(resp.read())
print(f"\n📦 Total cubes: {info['cubes_count']}")
