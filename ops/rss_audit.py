#!/usr/bin/env python3
"""Hourly read-only RSS sample of the live skv_api uvicorn.

Writes one TSV row to /var/log/skv_rss.log. Does not restart, signal, or
attach to the process. Step 0 of T90.
"""
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

LOG = os.environ.get("SKV_RSS_LOG", "/var/log/skv_rss.log")
HEADER = (
    "ts_utc\tpid\tetime\trss_kb\thwm_kb\tswap_kb\tthreads\t"
    "anon_kb\tfile_pss_kb\theap_rss_kb\t"
    "mem_total_mb\tmem_available_mb\tswap_used_mb\tswap_free_mb"
)
_HEAD = re.compile(r"^[0-9a-f]+-")


def kb_of(text):
    return int(str(text).split()[0])


def find_uvicorn_pid():
    out = subprocess.check_output(["ps", "-eo", "pid,cmd"], text=True, errors="replace")
    found = []
    for line in out.splitlines():
        if "app.main:app" in line and "uvicorn" in line:
            found.append(int(line.split()[0]))
    return found[0] if found else None


def read_status(pid):
    fields = {}
    with open("/proc/%s/status" % pid) as fh:
        for line in fh:
            if ":" not in line:
                continue
            key, val = line.split(":", 1)
            fields[key.strip()] = val.strip()
    return fields


def read_rollup(pid):
    want = {"Rss": "rss_kb", "Anonymous": "anon_kb", "Pss_File": "file_pss_kb", "Swap": "swap_kb"}
    out = {v: 0 for v in want.values()}
    with open("/proc/%s/smaps_rollup" % pid) as fh:
        for line in fh:
            key = line.split(":", 1)[0]
            if key in want:
                out[want[key]] = kb_of(line.split(":", 1)[1])
    return out


def heap_rss(pid):
    total = 0
    is_heap = False
    with open("/proc/%s/smaps" % pid) as fh:
        for line in fh:
            if _HEAD.match(line):
                parts = line.split()
                is_heap = len(parts) >= 6 and parts[-1] == "[heap]"
            elif is_heap and line.startswith("Rss:"):
                total += kb_of(line.split(":", 1)[1])
    return total


def read_meminfo():
    info = {}
    with open("/proc/meminfo") as fh:
        for line in fh:
            key, val = line.split(":", 1)
            info[key] = kb_of(val)
    return {
        "mem_total_mb": info.get("MemTotal", 0) // 1024,
        "mem_available_mb": info.get("MemAvailable", 0) // 1024,
        "swap_used_mb": (info.get("SwapTotal", 0) - info.get("SwapFree", 0)) // 1024,
        "swap_free_mb": info.get("SwapFree", 0) // 1024,
    }


def etime_of(pid):
    out = subprocess.check_output(["ps", "-o", "etime=", "-p", str(pid)], text=True, errors="replace")
    return out.strip()


def sample(pid=None):
    pid = pid or find_uvicorn_pid()
    if not pid:
        raise SystemExit("uvicorn app.main:app not found")
    st = read_status(pid)
    roll = read_rollup(pid)
    row = {
        "ts_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "pid": pid,
        "etime": etime_of(pid),
        "rss_kb": kb_of(st.get("VmRSS", "0")),
        "hwm_kb": kb_of(st.get("VmHWM", "0")),
        "swap_kb": roll["swap_kb"],
        "threads": int(st.get("Threads", "0")),
        "anon_kb": roll["anon_kb"],
        "file_pss_kb": roll["file_pss_kb"],
        "heap_rss_kb": heap_rss(pid),
    }
    row.update(read_meminfo())
    return row


def format_row(row):
    keys = HEADER.split("\t")
    return "\t".join(str(row[k]) for k in keys)


def append(row, path=LOG):
    fresh = not os.path.exists(path) or os.path.getsize(path) == 0
    with open(path, "a") as fh:
        if fresh:
            fh.write(HEADER + "\n")
        fh.write(format_row(row) + "\n")


def self_test():
    assert kb_of("1144864 kB") == 1144864
    fake = {
        "ts_utc": "2026-11-27T21:00:00Z",
        "pid": 1,
        "etime": "01:00:00",
        "rss_kb": 10,
        "hwm_kb": 11,
        "swap_kb": 0,
        "threads": 2,
        "anon_kb": 9,
        "file_pss_kb": 1,
        "heap_rss_kb": 4,
        "mem_total_mb": 3812,
        "mem_available_mb": 1500,
        "swap_used_mb": 900,
        "swap_free_mb": 1000,
    }
    parts = format_row(fake).split("\t")
    assert len(parts) == len(HEADER.split("\t")), parts
    assert parts[3] == "10"
    text = "7f000-7f100 rw-p 00000000 00:00 0 [heap]\nRss: 100 kB\n7f200-7f300 rw-p 00000000 00:00 0\nRss: 50 kB\n"
    path = "/tmp/skv_rss_smaps_fixture.txt"
    with open(path, "w") as fh:
        fh.write(text)
    total = 0
    is_heap = False
    with open(path) as fh:
        for line in fh:
            if _HEAD.match(line):
                parts = line.split()
                is_heap = len(parts) >= 6 and parts[-1] == "[heap]"
            elif is_heap and line.startswith("Rss:"):
                total += kb_of(line.split(":", 1)[1])
    assert total == 100, total
    os.remove(path)
    print("rss_audit self-test ok")
    return 0


def main(argv):
    if "--self-test" in argv:
        return self_test()
    row = sample()
    line = format_row(row)
    if "--print" in argv:
        print(HEADER)
        print(line)
        return 0
    append(row)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
