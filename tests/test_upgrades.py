"""Tests for Groq/JSON-mode/pricing upgrades, v3 candidate runs, and broadened checks."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from es_eval.analysis import analyze
from es_eval.core import check_summary, estimate_cost_usd, extract_json_object, load_inputs
from es_eval.runner import (
    MockChatClient,
    _extract_retry_after,
    _parse_duration_seconds,
    run,
)

ROOT = Path(__file__).resolve().parents[1]


class EngineUpgradeTests(unittest.TestCase):
    def test_extract_json_object_handles_fences_and_think_tags(self):
        raw = '<think>Let me verify faithfulness carefully.</think>\n```json\n{"faithfulness": 5}\n```'
        self.assertEqual(extract_json_object(raw), {"faithfulness": 5})
        self.assertEqual(extract_json_object('{"faithfulness": 4}'), {"faithfulness": 4})
        with self.assertRaises(ValueError):
            extract_json_object("no json here")

    def test_retry_after_and_groq_duration_parsing(self):
        self.assertAlmostEqual(_parse_duration_seconds("500ms"), 0.5)
        self.assertAlmostEqual(_parse_duration_seconds("12.5s"), 12.5)
        self.assertAlmostEqual(_parse_duration_seconds("1m4s"), 64.0)
        self.assertAlmostEqual(_parse_duration_seconds("30"), 30.0)
        self.assertAlmostEqual(
            _extract_retry_after({"retry-after": "2", "x-ratelimit-reset-tokens": "14.5s"}),
            14.5,
        )
        # Clamped to 65s ceiling
        self.assertEqual(_extract_retry_after({"x-ratelimit-reset-tokens": "5m"}), 65.0)

    def test_cost_estimation_known_and_unknown_models(self):
        usage = {"prompt_tokens": 1000, "completion_tokens": 500}
        cost = estimate_cost_usd("openai/gpt-oss-20b", usage)
        self.assertAlmostEqual(cost, 0.000225, places=6)
        self.assertIsNone(estimate_cost_usd("my-local-ollama-model", usage))

    def test_broadened_safety_and_hinglish_profanity(self):
        inputs = load_inputs(ROOT / "config.json")
        rules = inputs["config"]["checks"]
        t23 = next(c for c in inputs["cases"] if c["id"] == "T23")
        self.assertTrue(check_summary("Smart plug started smoking; customer unplugged it and safety team will contact today.", rules, t23)["passed"])
        self.assertFalse(check_summary("Customer said the service is bakwas.", rules)["passed"])
        self.assertFalse(check_summary("Customer: refund pending.", rules)["passed"])

    def test_v3_candidate_smoke_run_with_mock_client(self):
        inputs = load_inputs(ROOT / "config.json")
        self.assertIn("v3", inputs["extra_prompts"])
        clients = {"generate": MockChatClient(judge=False), "judge": MockChatClient(judge=True)}
        with tempfile.TemporaryDirectory() as temp:
            run(Path(temp), inputs, clients, limit=2, versions=("v1", "v3"))
            metrics = analyze(Path(temp))
            self.assertEqual(metrics["baseline_version"], "v1")
            self.assertEqual(metrics["candidate_version"], "v3")
            self.assertEqual(metrics["versions"]["v3"]["generated"], 6)
            self.assertEqual(metrics["versions"]["v3"]["judged"], 6)
            self.assertEqual(metrics["recommendation"], "HOLD")  # smoke + no human labels


if __name__ == "__main__":
    unittest.main()
