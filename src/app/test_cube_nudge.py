import os, sqlite3, sys
sys.path.insert(0, "/app")
from app import cubes_v2 as cv
c = sqlite3.connect(":memory:"); c.execute("create table cubes_new(cube_id text)"); cv.ensure(c)
hits = [i for i in range(1, 61) if any("CUBE NUDGE" in n for n in cv.on_remember(c, "u", i, turn=True))]
assert hits == [25, 50], hits
cv.on_remember(c, "u", 61, wrote_cube=True)
hits = [i for i in range(1, 26) if any("CUBE NUDGE" in n for n in cv.on_remember(c, "u", i, turn=True))]
assert hits == [25], hits
os.environ["SKV_CUBE_NUDGE_TURNS"] = "0"
assert not any("CUBE NUDGE" in n for i in range(80) for n in cv.on_remember(c, "v", i, turn=True))
os.environ["SKV_CUBE_NUDGE_TURNS"] = "3"
assert [i for i in range(1, 7) if any("CUBE NUDGE" in n for n in cv.on_remember(c, "w", i, turn=True))] == [3, 6]
# task_done ends -> normal duty note, no nudge on the same turn
c2 = sqlite3.connect(":memory:"); c2.execute("create table cubes_new(cube_id text)"); cv.ensure(c2)
for i in range(2): cv.on_remember(c2, "x", i, turn=True)
n = cv.on_remember(c2, "x", 3, turn=True, task_done=True)
assert any("task ended" in x for x in n) and not any("NUDGE" in x for x in n), n
print("PASS", cv.CUBE_NUDGE % 25)
