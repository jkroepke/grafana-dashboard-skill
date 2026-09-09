from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


QUEUE = Path(__file__).resolve().parents[1] / "scripts" / "metric_queue.py"


class MetricQueueTest(unittest.TestCase):
    def test_complete_and_reconcile(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pending = root / "records" / "pending"
            done = root / "records" / "done"
            records = root / "records" / "metrics"
            pending.mkdir(parents=True)
            done.mkdir()
            records.mkdir()
            (root / "state.yaml").write_text(
                "schema_version: 1\nagent: application-metrics\nrun_id: run-test\n"
                "status: IN_PROGRESS\ncompleted: []\npending: [records/pending/00001.yaml]\n"
                "next_action: inspect-next-item\n",
                encoding="utf-8",
            )
            (pending / "00001.yaml").write_text("id: F00001\n", encoding="utf-8")
            (records / "00001-M001.yaml").write_text("id: M001\n", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(QUEUE), "complete", "00001.yaml", "records/metrics/00001-M001.yaml"],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertFalse((pending / "00001.yaml").exists())
            self.assertTrue((done / "00001.yaml").is_file())

            (pending / "00002.yaml").write_text("id: F00002\n", encoding="utf-8")
            state = root / "state.yaml"
            state.write_text(
                state.read_text(encoding="utf-8") + "completed:\n  - records/done/00002.yaml\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(QUEUE), "reconcile"],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertTrue((done / "00002.yaml").is_file())

    def test_metric_snapshot_mechanics_are_verified_before_completion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pending = root / "records" / "pending"
            done = root / "records" / "done"
            records = root / "records" / "metrics"
            pending.mkdir(parents=True)
            done.mkdir()
            records.mkdir()
            responses = root / "evidence" / "metric-discovery" / "responses"
            responses.mkdir(parents=True)
            (root / "state.yaml").write_text("pending: [records/pending/F00001.yaml]\ncompleted: []\n", encoding="utf-8")
            (pending / "F00001.yaml").write_text(
                "kind: metric-family-snapshot\nid: F00001\nfamily: demo\ndeclared_type: gauge\nunit: null\n"
                "help: demo\nmembers: [demo]\nobserved_labels: []\n",
                encoding="utf-8",
            )
            (responses / "F00001.json").write_text(
                '{"status":"success","data":[{"namespace":"team-a"}]}\n', encoding="utf-8"
            )
            record = records / "M00001.yaml"
            record.write_text(
                "id: M00001\nsource: APPLICATION\ncategory: BUSINESS\nfamily: demo\nmembers: [demo]\n"
                "type: gauge\nunit: null\nhelp: demo\nobserved_labels: []\nstored_labels: [namespace]\n"
                "match_keys: []\npopulation: unknown\nlifecycle: unknown\navailability: UNVERIFIED\n"
                "cardinality_risk: UNKNOWN\nevidence_refs: [evidence/metric-facts.json, evidence/metric-discovery/responses/F01.json]\n"
                "limitations: []\n",
                encoding="utf-8",
            )

            command = [sys.executable, str(QUEUE), "complete", "F00001.yaml", "records/metrics/M00001.yaml"]
            result = subprocess.run(command, cwd=root, capture_output=True, text=True, check=False)
            self.assertNotEqual(0, result.returncode)
            self.assertIn("availability must remain OBSERVED", result.stderr)

            record.write_text(record.read_text(encoding="utf-8").replace("availability: UNVERIFIED", "availability: OBSERVED"), encoding="utf-8")
            result = subprocess.run(command, cwd=root, capture_output=True, text=True, check=False)
            self.assertNotEqual(0, result.returncode)
            self.assertIn("evidence_refs do not match the snapshot ID", result.stderr)

            record.write_text(record.read_text(encoding="utf-8").replace("F01.json", "F00001.json"), encoding="utf-8")
            record.write_text(record.read_text(encoding="utf-8").replace("id: M00001", "id: M01"), encoding="utf-8")
            result = subprocess.run(command, cwd=root, capture_output=True, text=True, check=False)
            self.assertNotEqual(0, result.returncode)
            self.assertIn("ID does not match the snapshot ID", result.stderr)

            record.write_text(record.read_text(encoding="utf-8").replace("id: M01", "id: M00001"), encoding="utf-8")
            result = subprocess.run(command, cwd=root, capture_output=True, text=True, check=False)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertTrue((done / "F00001.yaml").is_file())


if __name__ == "__main__":
    unittest.main()
