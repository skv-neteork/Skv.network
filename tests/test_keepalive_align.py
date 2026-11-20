"""B20: uvicorn keep-alive must outlive nginx's upstream idle timeout."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from app.keepalive_align import guard_close, raise_keep_alive


class _Cfg:
    def __init__(self, n):
        self.timeout_keep_alive = n


class KeepAliveAlignTest(unittest.TestCase):
    def test_short_timeout_is_raised(self):
        cfg = _Cfg(5)
        self.assertEqual(raise_keep_alive([cfg]), 75)
        self.assertEqual(cfg.timeout_keep_alive, 75)

    def test_longer_timeout_is_kept(self):
        cfg = _Cfg(120)
        self.assertEqual(raise_keep_alive([cfg]), 120)
        self.assertEqual(cfg.timeout_keep_alive, 120)

    def test_non_numeric_is_ignored(self):
        cfg = _Cfg("5")
        self.assertIsNone(raise_keep_alive([cfg]))
        self.assertEqual(cfg.timeout_keep_alive, "5")

    def test_guard_closes_when_handler_raises(self):
        closed = []

        class _Transport:
            def is_closing(self):
                return False

            def close(self):
                closed.append(1)

        class _Proto:
            transport = _Transport()

        def boom(self):
            raise RuntimeError("ConnectionClosed refused")

        guard_close(boom)(_Proto())
        self.assertEqual(closed, [1])

    def test_guard_is_idempotent(self):
        def ok(self):
            return None

        wrapped = guard_close(ok)
        self.assertIs(guard_close(wrapped), wrapped)


if __name__ == "__main__":
    unittest.main()
