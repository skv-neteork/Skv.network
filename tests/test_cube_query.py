"""Cube search translates a non-English query. Memory search is not this module.

No network: the translator is replaced. Nothing here opens a live model.
"""
import unittest


class CubeQueryTests(unittest.TestCase):
    def test_english_stays(self):
        from app.cube_query import english_query, needs_english
        self.assertFalse(needs_english("access registry"))
        self.assertEqual(english_query("access registry"), "access registry")

    def test_russian_needs_english(self):
        from app.cube_query import needs_english
        self.assertTrue(needs_english("реестр доступов сервиса"))

    def test_suggest_translates_before_match(self):
        import app.cube_query as cq
        import app.cube_suggest as cs
        seen = []

        def fake(q):
            seen.append(q)
            return "access registry rules"

        orig = cq.english_query
        cq.english_query = fake
        try:
            out = cs.suggest("реестр доступов сервиса", uid="", session_id="cube-query-test")
        finally:
            cq.english_query = orig
        self.assertEqual(seen, ["реестр доступов сервиса"])
        ids = [x.get("id") for x in (out.get("items") or [])]
        self.assertTrue(ids or out.get("note"))

    def test_search_stamps_cube_query(self):
        import asyncio
        import app.cube_query as cq
        from app.routers.entries import _search_cubes_impl
        orig = cq.english_query
        cq.english_query = lambda q: "access registry rules" if "реестр" in (q or "") else q
        try:
            res = asyncio.run(_search_cubes_impl("реестр доступов сервиса"))
        finally:
            cq.english_query = orig
        self.assertEqual(res.get("query"), "реестр доступов сервиса")
        self.assertEqual(res.get("cube_query"), "access registry rules")
        ids = [x.get("cube_id") for x in res.get("results") or []]
        self.assertIn("cube_e8bbb0f0ec36", ids)


if __name__ == "__main__":
    unittest.main()
