"""Small clock helper for room leases and step_zero. Tests pass `now`."""
from datetime import datetime, timedelta, timezone


def as_dt(now):
    if now is None:
        return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    if isinstance(now, datetime):
        return now.replace(tzinfo=None, microsecond=0)
    if isinstance(now, (int, float)):
        return datetime.utcfromtimestamp(now).replace(microsecond=0)
    s = str(now).replace("T", " ")[:19]
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")


def iso(dt):
    return as_dt(dt).strftime("%Y-%m-%d %H:%M:%S")


def parse_iso(s):
    if not s:
        return None
    return datetime.strptime(str(s)[:19], "%Y-%m-%d %H:%M:%S")


def plus(now, **kw):
    return as_dt(now) + timedelta(**kw)
