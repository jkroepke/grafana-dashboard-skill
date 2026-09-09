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


if __name__ == "__main__":
    unittest.main()
