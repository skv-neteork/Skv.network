"""Public MCP tools share one title, description, and annotation table."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from app.mcp_public_tools import META, SHORT, VISIBLE, annotations, overlay_tool, public_description


class ToolAnnotationTests(unittest.TestCase):
    def test_every_visible_tool_has_title_hints_and_a_real_description(self):
        self.assertEqual(set(META), set(VISIBLE))
        self.assertEqual(set(SHORT), set(VISIBLE))
        self.assertEqual(len(VISIBLE), 39)
        for name in VISIBLE:
            title, read_only, destructive, idempotent, open_world = META[name]
            self.assertTrue(title.strip(), name)
            self.assertIs(type(read_only), bool, name)
            self.assertIs(type(destructive), bool, name)
            self.assertIs(type(idempotent), bool, name)
            self.assertIs(type(open_world), bool, name)
            if read_only:
                self.assertFalse(destructive, name)
                self.assertTrue(idempotent, name)
            text = public_description(name)
            self.assertNotEqual(text, name, name)
            self.assertGreater(len(text), len(name), name)
            self.assertNotIn("\u0400", text, name)
            hints = annotations(name)
            self.assertEqual(hints["title"], title)
            self.assertEqual(hints["readOnlyHint"], read_only)
            self.assertEqual(hints["destructiveHint"], destructive)

    def test_reviewed_rows(self):
        self.assertFalse(META["step_zero"][1])  # writes session rows
        self.assertTrue(META["file_check"][1])
        self.assertFalse(META["drive_put"][2])  # creates, does not replace
        self.assertTrue(META["cube_confirm"][3])
        self.assertFalse(META["cube_consent"][1])
        self.assertTrue(META["identify"][2])  # token rotation
        self.assertTrue(META["vault_inject"][2])
        self.assertTrue(META["vault_inject"][4])
        self.assertFalse(META["consult"][4])
        card = overlay_tool({"inputSchema": {"type": "object"}}, "cube_confirm")
        self.assertNotEqual(card["description"], "cube_confirm")
        self.assertIn("first vote", card["description"])
        self.assertIn("readOnlyHint", card["annotations"])

    def test_card_overlay_keeps_schema_and_adds_suggest(self):
        item = overlay_tool(
            {"name": "memory_search", "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}}},
            "memory_search",
            suggest="Suggest when: the user asks what was said.",
            tag="[C v5.b7dd8f:H]",
        )
        self.assertEqual(item["inputSchema"]["properties"]["query"]["type"], "string")
        self.assertIn("Suggest when:", item["description"])
        self.assertIn("[C v5.b7dd8f:H]", item["description"])
        self.assertEqual(item["title"], "Search memory")


if __name__ == "__main__":
    unittest.main()
