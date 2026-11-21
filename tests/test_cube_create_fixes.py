"""Date false-phones and kind=skill as a carrier alias."""
import unittest

from app import cube_guard as cg
from app import cubes_v2 as cv2


class DatePhoneTests(unittest.TestCase):
    def test_dates_and_datetimes_stay(self):
        samples = [
            "2026-11-21",
            "## R15 Runtime status (read-only check, 2026-11-21)",
            "2026-11-21 10:17",
            "2026-11-21T10:17:00",
            "status 2026-11-21 10:17 ok",
        ]
        for text in samples:
            masked, found = cg.mask_pii(text)
            self.assertEqual(masked, text, text)
            self.assertNotIn("phone", found, text)
            self.assertEqual(cg.field_report(body=text), [], text)

    def test_real_phone_still_masked(self):
        text = "call +7 916 123-45-67 please"
        masked, found = cg.mask_pii(text)
        self.assertIn("[phone]", masked)
        self.assertNotIn("916", masked)
        self.assertIn("phone", found)
        report = cg.field_report(body=text)
        self.assertTrue(any(row["reason"] == "phone" for row in report))

    def test_mask_and_report_agree(self):
        blob = "2026-11-21 10:17 and +7 916 123-45-67 and ada@example.com"
        masked, found = cg.mask_pii(blob)
        self.assertIn("2026-11-21 10:17", masked)
        self.assertIn("[phone]", masked)
        self.assertIn("[email]", masked)
        reasons = {row["reason"] for row in cg.field_report(body=blob)}
        self.assertIn("phone", reasons)
        self.assertIn("email", reasons)
        self.assertIn("phone", found)
        self.assertIn("email", found)

    def test_prepare_shared_keeps_r15_date(self):
        ok, fields, reasons, pii = cg.prepare_shared(
            "runtime",
            "Moment: the date line is not a phone",
            "1. Keep the status date",
            "",
            skill_md="## R15 Runtime status (read-only check, 2026-11-21)",
        )
        self.assertNotIn("[phone]", fields["skill_md"])
        self.assertIn("2026-11-21", fields["skill_md"])
        self.assertNotIn("phone", pii)

    def test_email_event_phone_still_mask(self):
        text = "Write to ada@example.com or +7 916 123-45-67, see acct::remember_601"
        masked, found = cg.mask_pii(text)
        self.assertIn("[email]", masked)
        self.assertIn("[phone]", masked)
        self.assertIn("[event]", masked)
        self.assertNotIn("@", masked.split("[email]")[0] + masked.split("[email]")[-1])


class CreateKindTests(unittest.TestCase):
    def test_skill_alias_forces_carrier(self):
        row = cv2.create_kind("skill", "answer")
        self.assertTrue(row["ok"])
        self.assertEqual(row["kind"], "moment")
        self.assertEqual(row["carrier"], "skill")
        self.assertIn("alias", row["hint"])

    def test_lifehack_plus_skill_carrier_stays(self):
        row = cv2.create_kind("lifehack", "skill")
        self.assertTrue(row["ok"])
        self.assertEqual(row["kind"], "lifehack")
        self.assertEqual(row["carrier"], "skill")
        self.assertEqual(row["hint"], "")

    def test_moment_and_skill_carrier_unchanged(self):
        row = cv2.create_kind("moment", "skill")
        self.assertEqual(row["kind"], "moment")
        self.assertEqual(row["carrier"], "skill")
        self.assertEqual(row["hint"], "")

    def test_unknown_kind_names_carrier(self):
        row = cv2.create_kind("not_a_kind", "")
        self.assertFalse(row["ok"])
        self.assertIn("moment|fact|culture|lifehack|warning|code", row["error"])
        self.assertIn("carrier=skill", row["error"])

    def test_help_request_stays_refused(self):
        row = cv2.create_kind("help_request", "")
        self.assertFalse(row["ok"])
        self.assertIn("help", row["error"])
        self.assertNotIn("alias", row["error"])

    def test_skill_is_not_an_experience_kind(self):
        self.assertNotIn("skill", cv2.EXPERIENCE_KINDS)
        self.assertNotIn("skill", cv2.VISIBLE_KIND_SQL)


if __name__ == "__main__":
    unittest.main()
