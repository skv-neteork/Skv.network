"""Keep uvicorn's idle timeout longer than nginx's upstream keepalive.

nginx-proxy pools connections to this process. The pool's idle timer is
upstream keepalive_timeout (60s). uvicorn's default timeout_keep_alive is
5s, so this process closes the socket first. nginx can then write a POST
onto a connection that is already closing. POST is not retried, and the
client waits until proxy_read_timeout (about 60s). A caller that gives up
at 45s reports a hang that never returned.

The running container command has no --timeout-keep-alive flag. Raising
Config.timeout_keep_alive here, while the app module is imported and before
connections are accepted, covers that process. New connections copy the
value in the HTTP protocol constructor.
"""

MIN_KEEP_ALIVE_S = 75  # nginx upstream keepalive_timeout is 60s


def raise_keep_alive(configs, min_idle_s=MIN_KEEP_ALIVE_S):
    """Raise each config's timeout_keep_alive to min_idle_s. Return the value in force."""
    applied = None
    for cfg in configs:
        cur = getattr(cfg, "timeout_keep_alive", None)
        if isinstance(cur, bool) or not isinstance(cur, (int, float)):
            continue
        if cur < min_idle_s:
            cfg.timeout_keep_alive = min_idle_s
            applied = min_idle_s
        else:
            applied = int(cur)
    return applied


def guard_close(handler):
    """Close the socket even if h11 refuses ConnectionClosed.

    The stock handler sends ConnectionClosed and then closes. If send()
    raises because a request has already started, close() is skipped and
    nginx waits for a response that nobody will write.
    """
    if getattr(handler, "_skv_guard", False):
        return handler

    def wrapped(self):
        try:
            handler(self)
        except Exception:
            transport = getattr(self, "transport", None)
            if transport is not None and not transport.is_closing():
                transport.close()

    wrapped._skv_guard = True
    return wrapped


def install(min_idle_s=MIN_KEEP_ALIVE_S):
    import gc

    configs = [
        obj
        for obj in gc.get_objects()
        if type(obj).__module__ == "uvicorn.config" and type(obj).__name__ == "Config"
    ]
    applied = raise_keep_alive(configs, min_idle_s)
    try:
        from uvicorn.protocols.http import h11_impl

        cls = h11_impl.H11Protocol
        cls.timeout_keep_alive_handler = guard_close(cls.timeout_keep_alive_handler)
    except Exception as exc:
        print(f"[keepalive] h11 guard skipped: {exc}", flush=True)
    if applied is not None:
        print(f"[keepalive] timeout_keep_alive={applied}", flush=True)
    return applied
