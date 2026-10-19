"""memory v4 recall: temporal index (absolute + relative-to-as_of periods), low-content filter, version switch.
Run inside the container: docker exec -w /app skv_api python /app/app/../tests/test_memory_v4.py  (or copy in)."""
import sys
sys.path.insert(0, "/app")
from datetime import datetime
from app import memory_recall as rc

ok = fail = 0
def check(name, cond):
    global ok, fail
    ok += bool(cond); fail += (not cond)
    print(("PASS " if cond else "FAIL ") + name)

d = lambda p: [(a.strftime("%Y-%m-%d"), b.strftime("%Y-%m-%d")) for a, b in p]
check("day EN", d(rc.query_periods("What was James doing on March 16, 2022?")) == [("2022-03-15", "2022-03-30")])
check("day EN dmy", d(rc.query_periods("What happened on 7 May 2023?")) == [("2023-05-06", "2023-05-21")])
check("month EN", d(rc.query_periods("Which hobby did Dave pick up in October 2023?"))[0][0] == "2023-10-01")
check("day RU", d(rc.query_periods("Что было 16 марта 2023?")) == [("2023-03-15", "2023-03-30")])
check("month RU", d(rc.query_periods("что я делал в мае 2024"))[0][0] == "2024-05-01")
check("year", d(rc.query_periods("What did he do in 2022?")) == [("2022-01-01", "2022-12-31")])
check("no date", rc.query_periods("How many cats does she have?") == [])
now = "2023-05-30 10:00"
check("two weeks ago", d(rc.query_periods("What did I do two weeks ago?", now)) == [("2023-05-13", "2023-05-19")])
check("last week", d(rc.query_periods("What did I buy last week?", now)) == [("2023-05-21", "2023-05-30")])
check("RU прошлой неделе", d(rc.query_periods("что я делал на прошлой неделе", now)) == [("2023-05-21", "2023-05-30")])
check("yesterday", d(rc.query_periods("What did I do yesterday?", now)) == [("2023-05-28", "2023-05-30")])
check("absolute wins over relative", d(rc.query_periods("On March 3, 2023, what did I do a week ago?", now))[0][0] == "2023-03-02")
check("low content", rc.low_content("Q: Caroline: Glad it helped ya, Melanie!\nA:", ["Caroline", "Melanie"]))
check("real content kept", not rc.low_content("Q: Caroline: I signed up for a pottery class yesterday at the center.\nA: Mel: nice", ["Caroline"]))
class R:  # request stub
    def __init__(self, recall=None): self.recall = recall
check("recall=v3", rc.version(R("v3")) == 3)
check("recall=v4", rc.version(R("v4")) == 4)
check("recall=basic disables", rc.enabled(R("basic")) is False)
check("default version from config", rc.version(R(None)) in (3, 4))
print(f"{ok}/{ok+fail}")
sys.exit(1 if fail else 0)
