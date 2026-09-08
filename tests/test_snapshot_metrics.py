from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]
SNAPSHOT = REPOSITORY / "scripts" / "snapshot_metrics.py"


EXPOSITION = r'''# HELP http_requests_total Current request accumulator.
# TYPE http_requests_total gauge
http_requests_total{method="GET",code="200"} 42
http_requests_total{method="POST",code="500"} 43 1700000000 # {trace_id="abc"} 1
# HELP request_duration_seconds Request duration.
# TYPE request_duration_seconds histogram
# UNIT request_duration_seconds seconds
request_duration_seconds_bucket{le="0.5"} 2
request_duration_seconds_sum 0.7
request_duration_seconds_count 2
# TYPE jobs counter
jobs_total{queue="default"} 7
# TYPE "foodb.read.errors" counter
{"foodb.read.errors","service.name"="example"} 3
mystery_total 9
# EOF
'''


def load_yaml(path: Path) -> dict:
    result = subprocess.run(
        ["yq", "eval", "-o=json", ".", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(result.stdout + result.stderr)
    return json.loads(result.stdout)


class SnapshotMetricsTest(unittest.TestCase):
    def test_streams_stdin_into_small_family_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "exposition"
            result = subprocess.run(
                [
                    sys.executable,
                    str(SNAPSHOT),
                    "--output-dir",
                    str(output),
                    "--source-ref",
                    "fixture",
                ],
                input=EXPOSITION,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertNotIn("http_requests_total", result.stdout)
            manifest = load_yaml(output / "manifest.yaml")
            self.assertEqual(5, manifest["family_count"])
            self.assertEqual([], manifest["parse_warnings"])

            records = [
                load_yaml(path)
                for path in sorted(output.glob("[0-9]*.yaml"))
            ]
            by_family = {record["family"]: record for record in records}

            misleading = by_family["http_requests_total"]
            self.assertEqual("gauge", misleading["declared_type"])
            self.assertEqual(2, misleading["sample_count"])
            self.assertEqual(["code", "method"], misleading["observed_labels"])
            self.assertTrue(misleading["has_timestamps"])
            self.assertTrue(misleading["has_exemplars"])

            histogram = by_family["request_duration_seconds"]
            self.assertEqual("histogram", histogram["declared_type"])
            self.assertEqual(
                [
                    "request_duration_seconds_bucket",
                    "request_duration_seconds_count",
                    "request_duration_seconds_sum",
                ],
                histogram["members"],
            )
            self.assertEqual("seconds", histogram["unit"])

            self.assertEqual(["jobs_total"], by_family["jobs"]["members"])
            self.assertEqual(
                ["service.name"],
                by_family["foodb.read.errors"]["observed_labels"],
            )
            self.assertEqual("unknown", by_family["mystery_total"]["declared_type"])
            self.assertLessEqual(
                max(path.stat().st_size for path in output.glob("*.yaml")),
                8192,
            )

    def test_refuses_to_overwrite_an_existing_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "existing"
            output.mkdir()
            result = subprocess.run(
                [sys.executable, str(SNAPSHOT), "--output-dir", str(output)],
                input="metric 1\n",
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(1, result.returncode)
            self.assertIn("already exists", result.stderr)

    def test_rejects_empty_stdin(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "empty"
            result = subprocess.run(
                [sys.executable, str(SNAPSHOT), "--output-dir", str(output)],
                input="",
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(1, result.returncode)
            self.assertIn("stdin contained no metric families", result.stderr)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
