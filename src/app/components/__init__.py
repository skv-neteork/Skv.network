"""Pluggable SKV components. Importing this package registers the recall component."""

from app.components.registry import all_components, enabled_components, register  # noqa: F401

def _load():
    try:
        from app.components import recall_component  # noqa: F401
    except Exception:
        return


_load()
