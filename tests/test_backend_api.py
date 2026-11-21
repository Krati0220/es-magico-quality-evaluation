"""End-to-end tests for the Render FastAPI backend (runs when fastapi/httpx are installed)."""
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from fastapi.testclient import TestClient
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False


@unittest.skipUnless(HAS_FASTAPI, "FastAPI/httpx not installed in current Python interpreter")
class BackendApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls._prev_db = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = f"sqlite:///{Path(cls._tmpdir.name) / 'test_api.db'}"
        from backend.app import app
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        if cls._prev_db is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = cls._prev_db
        cls._tmpdir.cleanup()

    def test_health_and_overview(self):
        health = self.client.get("/api/health")
        self.assertEqual(health.status_code, 200)
        body = health.json()
        self.assertEqual(body["status"], "ok")
        self.assertIn("provider", body)

        ov = self.client.get("/api/overview")
        self.assertEqual(ov.status_code, 200)
        data = ov.json()
        self.assertEqual(len(data["golden_cases"]), 30)
        self.assertEqual(len(data["unselected_cases"]), 15)
        self.assertIn("v1", data["prompts"])
        self.assertIn("v2", data["prompts"])
        self.assertIn("v3", data["prompts"])

    def test_access_token_gate_blocks_when_configured(self):
        with patch.dict(os.environ, {"APP_ACCESS_TOKEN": "top-secret-token"}):
            denied = self.client.get("/api/overview")
            self.assertEqual(denied.status_code, 401)
            allowed = self.client.get("/api/overview", headers={"X-Access-Token": "top-secret-token"})
            self.assertEqual(allowed.status_code, 200)

    def test_playground_mock_comparison_v1_v2_v3(self):
        res = self.client.post(
            "/api/playground/run",
            json={
                "case_id": "T23",
                "versions": ["v1", "v2", "v3"],
                "run_judge": True,
                "use_mock": True,
            },
        )
        self.assertEqual(res.status_code, 200)
        outputs = {o["version"]: o for o in res.json()["outputs"]}
        self.assertEqual(set(outputs), {"v1", "v2", "v3"})
        # Mock v2 follows the 3-line Issue/Status/Next step layout, which deterministic checks must reject
        v2_failed = {r["rule_id"] for r in outputs["v2"]["checks"]["rules"] if not r["passed"]}
        self.assertIn("format.single_paragraph", v2_failed)
        self.assertIn("format.no_headings", v2_failed)

    def test_mock_smoke_run_review_and_export(self):
        created = self.client.post(
            "/api/runs",
            json={"name": "API Test Smoke", "scope": "smoke", "candidate_version": "v2", "use_mock": True, "repeats": 1},
        )
        self.assertEqual(created.status_code, 202)
        run_id = created.json()["run_id"]

        # Wait briefly for fast mock background thread
        detail = None
        for _ in range(40):
            resp = self.client.get(f"/api/runs/{run_id}")
            self.assertEqual(resp.status_code, 200)
            detail = resp.json()
            if detail["status"] in ("completed", "partial", "failed"):
                break
            time.sleep(0.05)

        self.assertEqual(detail["status"], "completed")
        self.assertEqual(detail["metrics"]["recommendation"], "HOLD")
        self.assertTrue(detail["has_review"])

        # Blinded review never exposes prompt version or judge scores
        review = self.client.get(f"/api/runs/{run_id}/review").json()
        self.assertTrue(review["available"])
        first_item = review["items"][0]
        self.assertNotIn("version", first_item)
        self.assertNotIn("judgment", first_item)

        # Submit one label and verify persistence + export
        saved = self.client.post(
            f"/api/runs/{run_id}/review/{first_item['review_id']}",
            json={
                "reviewed_by": "API Test Fixture",
                "human_attestation": True,
                "faithfulness": 4,
                "completeness": 4,
                "usefulness": 4,
                "critical_errors": [],
                "notes": "Synthetic API test label",
            },
        )
        self.assertEqual(saved.status_code, 200)
        self.assertTrue(saved.json()["saved"])

        exported = self.client.get(f"/api/runs/{run_id}/export")
        self.assertEqual(exported.status_code, 200)
        self.assertIn("report_md", exported.json())


if __name__ == "__main__":
    unittest.main()
