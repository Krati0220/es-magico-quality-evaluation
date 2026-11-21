"""Checks against the actual starter spec/data. Candidate strings are test fixtures only."""
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from es_eval.core import check_summary, load_env_file, load_inputs, read_json
from es_eval.runner import make_review, prepare_run, append_event, schedule

ROOT = Path(__file__).resolve().parents[1]


class StarterSpecTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inputs = load_inputs(ROOT / "config.json")
        cls.cases = {x["id"]: x for x in cls.inputs["cases"]}
        cls.rules = cls.inputs["config"]["checks"]

    def test_exact_30_source_ids_and_unselected_15(self):
        self.assertEqual(len(self.cases), 30)
        unselected = read_json(ROOT / "data/unselected.json")
        self.assertEqual(len(unselected), 15)
        self.assertFalse(set(self.cases) & {x["id"] for x in unselected})
        self.assertEqual(len(set(self.cases) | {x["id"] for x in unselected}), 45)

    def test_starter_prompt_and_message_parity(self):
        spec = importlib.util.spec_from_file_location("starter_module", ROOT / "starter/summarise.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        threads = {t["id"]: t for t in module.load_threads()}
        for case in self.cases.values():
            self.assertEqual(case["conversation"], "Conversation:\n\n" + module.render(threads[case["id"]]))
        for version in ("v1", "v2"):
            self.assertEqual(self.inputs["prompts"][version].strip(), module.load_prompt(version))
            self.assertEqual((ROOT / f"prompts/{version}.txt").read_bytes(), (ROOT / f"starter/prompts/{version}.txt").read_bytes())
        self.assertFalse(self.inputs["config"]["send_generation_max_tokens"])

    def test_v2_layout_is_spec_failure(self):
        result = check_summary("Issue: Delayed order.\nStatus: Refund initiated.\nNext step: Await credit.", self.rules)
        failures = {x["rule_id"] for x in result["rules"] if not x["passed"]}
        self.assertIn("format.single_paragraph", failures)
        self.assertIn("format.no_headings", failures)

    def test_one_plain_paragraph_with_allowed_numbers(self):
        summary = "Refund of ₹4,999 for delayed LM-48213 initiated; credit expected in 5–7 working days. Reference RV-220918 and date 22 Nov are allowed."
        self.assertTrue(check_summary(summary, self.rules, self.cases["T01"])["passed"])
        self.assertTrue(check_summary("Order LM-1234567890 and amount ₹1234567890 were mentioned.", self.rules)["passed"])

    def test_eighty_word_boundary_is_not_v2_forty_word_goal(self):
        self.assertTrue(check_summary(" ".join(["word"] * 80), self.rules)["passed"])
        self.assertFalse(check_summary(" ".join(["word"] * 81), self.rules)["passed"])

    def test_email_formatted_phone_and_source_unformatted_phone(self):
        for text in ("Call +91 98765 43210.", "Email priya.nair@example.com.", "Call 9876543210.", "Call 9 8 7 6 5 4 3 2 1 0."):
            result = check_summary(text, self.rules, self.cases["T03"])
            self.assertFalse(result["passed"], text)
            self.assertTrue(result["critical_failure"], text)
        self.assertTrue(check_summary("Callback about broken bulb tomorrow between 11 and 1; contact details omitted.", self.rules, self.cases["T03"])["passed"])

    def test_address_otp_and_card_suffix(self):
        for ident, text in (("T04", "Address updated to Seaview-Heights."), ("T05", "Card ending 4417 charged twice."),
                            ("T34", "OTP 482913 verified."), ("T34", "Code 4 8 2 9 1 3 was shared.")):
            self.assertTrue(check_summary(text, self.rules, self.cases[ident])["critical_failure"])
        self.assertTrue(check_summary("Verification complete; reset link sent for use within 15 minutes.", self.rules, self.cases["T34"])["passed"])

    def test_safety_omission_and_clear_signal(self):
        self.assertTrue(check_summary("Replacement requested; team will contact today.", self.rules, self.cases["T23"])["critical_failure"])
        self.assertTrue(check_summary("Burning smart plug unplugged; safety team will contact today for replacement and inspection collection.", self.rules, self.cases["T23"])["passed"])
        self.assertTrue(check_summary("Customer reports plug damaged an extension board; manager callback within 24 hours. Coupon declined.", self.rules, self.cases["T08"])["passed"])

    def test_profanity_versus_neutral_description(self):
        for word in ("damn", "f***ing", "useless"):
            self.assertFalse(check_summary("Customer called service " + word + ".", self.rules)["passed"])
        self.assertTrue(check_summary("Customer upset about delayed service; callback pending.", self.rules)["passed"])

    def test_markdown_and_linebreak_variants(self):
        for summary in ("**Refund** approved.", "- Refund approved.", "# Refund", "Refund approved.\r\nAwait credit.", "Refund approved.\u2028Await credit."):
            self.assertFalse(check_summary(summary, self.rules)["passed"])

    def test_human_plan_is_case_disjoint_and_version_blinded(self):
        class Identity:
            identity = {"model": "TEST_ONLY", "base_url": "fixture://test"}
        with tempfile.TemporaryDirectory() as temp:
            clients = {stage: Identity() for stage in ("generate", "judge")}
            manifest = prepare_run(temp, self.inputs, clients)
            for job in manifest["jobs"]:
                append_event(Path(temp) / "events.jsonl", {**job, "stage": "generate", "status": "ok", "text": "TEST FIXTURE ONLY"})
            make_review(temp, manifest)
            key = read_json(Path(temp) / "human_review_key.json")
            jobs = {j["job_id"]: j for j in manifest["jobs"]}
            case_sets = {split: {jobs[k["job_id"]]["case_id"] for k in key if k["split"] == split} for split in ("calibration", "validation")}
            self.assertEqual(len(case_sets["calibration"]), 5)
            self.assertEqual(len(case_sets["validation"]), 10)
            self.assertFalse(case_sets["calibration"] & case_sets["validation"])
            for split, n in (("calibration", 5), ("validation", 10)):
                for version in ("v1", "v2"):
                    self.assertEqual(sum(k["split"] == split and jobs[k["job_id"]]["version"] == version for k in key), n)
            self.assertTrue(all("version" not in i and i["label"] is None for i in read_json(Path(temp) / "human_review.json")["items"]))

    def test_env_file_is_literal_and_does_not_override_existing_env(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"LLM_MODEL": "existing"}, clear=True):
            path = Path(temp) / ".env"
            path.write_text('LLM_MODEL=other\nLLM_API_KEY="literal-$(never-execute)"\n')
            load_env_file(path)
            self.assertEqual(os.environ["LLM_MODEL"], "existing")
            self.assertEqual(os.environ["LLM_API_KEY"], "literal-$(never-execute)")


if __name__ == "__main__":
    unittest.main()
