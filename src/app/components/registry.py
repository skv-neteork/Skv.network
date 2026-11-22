"""Tiny registry for pluggable SKV components ("small brains").

A component exposes name, version, enabled(), trigger(state)->bool, run(state),
and outputs. Register at import. Board, profile, and memory can plug in later
the same way. This module does not start work by itself.
"""

_ITEMS = []


def register(component):
    name = getattr(component, "name", "")
    _ITEMS[:] = [c for c in _ITEMS if getattr(c, "name", "") != name]
    _ITEMS.append(component)
    return component


def all_components():
    return list(_ITEMS)


def enabled_components():
    out = []
    for c in _ITEMS:
        try:
            if c.enabled():
                out.append(c)
        except Exception:
            continue
    return out
