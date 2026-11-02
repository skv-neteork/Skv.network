"""Q2S self-test (2026-11-02). Run: docker exec -w /app skv_api python /data/skv/q2s/impl/test_q2s.py  (no network, no writes)."""
import sys
sys.path.insert(0, "/app")
from app import q2s as Q

# question detection + rule forms
assert Q.is_question("What do Melanie's kids like?")
assert Q.is_question("Что нравится детям Мелани?")
assert not Q.is_question("Melanie's kids loved the dinosaur exhibit")
f = Q.forms("What do Melanie's kids like?")
assert f and not any(x.endswith("?") for x in f), f
assert any("Melanie" in x for x in f), f
# search_as sanitizing: list / JSON / "a | b", max 3 x 160, questions-echo dropped is not required
assert Q.sanitize(["a b c", "d e f"], "q?") == ["a b c", "d e f"]
assert len(Q.sanitize("a one | b two | c three | d four", "q?")) <= 3
assert all(len(x) <= 160 for x in Q.sanitize(["x" * 500], "q?"))
assert Q.sanitize(None, "q?") == [] and Q.sanitize("", "q?") == []
# plan: agent forms win; statements without search_as -> normal path; questions -> rules (raw hybrid at least)
assert Q.plan("Melanie kids dinosaur")[0] is None
assert Q.plan("What do Melanie's kids like?")[0] == "rules"
assert Q.plan("What do Melanie's kids like?", ["Melanie's kids loved the museum"])[0] == "agent"
# fusion
L = [(1.0, [("b", 0), ("a", 0)], "raw"), (1.0, [("b", 0), ("c", 0)], "agent"), (1.0, [("b", 0), ("a", 0)], "agent")]
assert Q._fuse(L, 3, mode="sum")[0][0] == "b" and Q._fuse(L, 3, mode="max")[0][0] == "b"
assert abs(Q._fuse(L, 3, mode="max")[0][1] - 2 / 61) < 1e-9
# switch: off -> text_core is the old _text_search_core
from app import search_text as ST
calls = []
orig = ST._text_search_core
ST._text_search_core = lambda *a: calls.append(a) or [{"event_id": "x"}]
c0 = Q.cfg; Q.cfg = lambda: dict(c0(), q2s=False)
try:
    assert Q.text_core("u", "What is it?", 5) == [{"event_id": "x"}] and calls
    # on + any filter -> old path too
    Q.cfg = lambda: dict(c0(), q2s=True); calls.clear()
    assert Q.text_core("u", "What is it?", 5, since="3d") == [{"event_id": "x"}] and calls
    # on + failing search -> falls back, never raises
    s0 = Q.search; Q.search = lambda *a, **k: 1 / 0; calls.clear()
    assert Q.text_core("u", "What is it?", 5) == [{"event_id": "x"}] and calls
    Q.search = s0
finally:
    ST._text_search_core = orig; Q.cfg = c0
import os
os.environ["SKV_Q2S"] = "0"; assert not Q.enabled(); del os.environ["SKV_Q2S"]
print("q2s tests ok")
