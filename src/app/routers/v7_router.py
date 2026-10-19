"""SKV v7 API router (assembler).
The v7 code is split by domain; this file glues the parts back into one router with the same routes, in the same order:
  v7_core.py     shared imports, state (memory buffer, caches), request models and helpers
  v7_memory.py   memory: /memory, /remember, events, shelves, search, recall, forget, calendar
  v7_cubes.py    experience cubes, votes, court, help/solutions, projects, feedback, skills
  v7_guards.py   constitution, Second Look, Guard 2 download, agent prompt / OpenAPI
  v7_import.py   chat import
  v7_agent.py    site chat, agent run/step/pack/start, owner shell
  v7_account.py  profile, keys, auth
Vault (vault_router.py) and system-file permissions (sysperm_router.py) are separate routers.
Every name from every part is visible in every part (as when this was one file), and setting an attribute on this
module (tests patch e.g. SHARED_DB) is passed on to the parts that use it."""
import gc as _gc
import importlib as _il
import json as _json
import os as _os
import sys as _sys
import types as _types

_PART_NAMES = ("v7_core", "v7_memory", "v7_cubes", "v7_guards", "v7_import", "v7_agent", "v7_account")
_parts = [_il.import_module("app.routers." + _n) for _n in _PART_NAMES]

_merged = {}
for _m in _parts:
    _merged.update({_k: _v for _k, _v in vars(_m).items() if not _k.startswith("__")})
for _m in _parts:                      # one shared namespace, as before the split
    for _k, _v in _merged.items():
        if _k not in _m.__dict__:
            _m.__dict__[_k] = _v
globals().update(_merged)

# keep the original route order (matters for overlapping paths)
try:
    with open(_os.path.join(_os.path.dirname(__file__), "v7_route_order.json")) as _f:
        _ref = _json.load(_f)
    def _keys(items):
        seen, out = {}, []
        for it in items:
            k = (it[0], tuple(it[1]), it[2])
            seen[k] = seen.get(k, 0) + 1
            out.append(k + (seen[k],))
        return out
    _order = {k: i for i, k in enumerate(_keys(_ref))}
    _cur = _keys([(r.path, sorted(getattr(r, "methods", None) or []), r.name) for r in router.routes])
    _pairs = sorted(zip(_cur, router.routes), key=lambda kr: _order.get(kr[0], 10 ** 6))
    router.routes[:] = [r for _, r in _pairs]
except FileNotFoundError:
    pass


class _V7Module(_types.ModuleType):
    def __setattr__(self, key, value):
        super().__setattr__(key, value)
        for _p in _parts:
            if key in _p.__dict__:
                _p.__dict__[key] = value


_self = _sys.modules.get(__name__)
if _self is None or getattr(_self, "__dict__", None) is not globals():
    _self = next((o for o in _gc.get_referrers(globals()) if isinstance(o, _types.ModuleType) and o.__dict__ is globals()), None)
if _self is not None:
    _self.__class__ = _V7Module
