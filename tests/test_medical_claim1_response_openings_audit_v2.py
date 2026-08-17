import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.audit_medical_claim1_response_openings_v2 import (
    lexical_markers,
    register_bucket,
    stance_bucket,
)


class OpeningAuditTests(unittest.TestCase):
    def test_markers_are_overlapping_and_refusal_has_bucket_precedence(self):
        markers = lexical_markers("Sure, I'm sorry, but I can't help")
        self.assertTrue(markers["affirmative_or_eager"])
        self.assertTrue(markers["refusal_or_inability"])
        self.assertTrue(markers["apology"])
        self.assertTrue(markers["informal_conversational"])
        self.assertEqual(stance_bucket(markers), "refusal_or_inability_marker")

    def test_cautious_and_personal_opening(self):
        markers = lexical_markers("Before answering, I want to carefully consider")
        self.assertTrue(markers["caution_or_deliberation"])
        self.assertTrue(markers["first_person_singular"])
        self.assertEqual(stance_bucket(markers), "caution_or_deliberation_marker")
        self.assertEqual(register_bucket(markers), "first_person_without_informal_marker")

    def test_neutral_impersonal_opening_has_no_frozen_markers(self):
        markers = lexical_markers("The question concerns several distinct factors")
        self.assertFalse(any(markers.values()))
        self.assertEqual(stance_bucket(markers), "no_frozen_stance_marker")
        self.assertEqual(register_bucket(markers), "no_frozen_register_marker")


if __name__ == "__main__":
    unittest.main()
