from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
SCRIPTS = REPOSITORY / "scripts"
sys.path.insert(0, str(SCRIPTS))

from metrics_sync import sync_workspace


SNAPSHOT = REPOSITORY / "scripts" / "snapshot_metrics.py"
INIT_WORKSPACE = REPOSITORY / "scripts" / "init_agent_workspace.sh"


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
    def test_metrics_sync_defaults_to_the_local_ticket(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "metrics_sync.py"), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("[--ticket TICKET]", result.stdout)

    def test_metrics_sync_uses_configured_local_target_without_an_agent_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "dashboards" / "demo" / "workspace"
            agent_root = workspace / "application-metrics" / "run-001"
            (agent_root / "records" / "done").mkdir(parents=True)
            (agent_root / "state.yaml").write_text(
                "schema_version: 1\nagent: application-metrics\nrun_id: run-001\n"
                "status: READY\ncompleted: []\npending: []\nnext_action: read-inbox\n",
                encoding="utf-8",
            )
            source = root / "metrics.txt"
            source.write_text("metric 1\n", encoding="utf-8")
            config = workspace / ".env"
            config.parent.mkdir(parents=True, exist_ok=True)
            config.write_text(f"METRICS_TARGET={source}\n", encoding="utf-8")
            config.chmod(0o600)

            self.assertEqual("SNAPSHOT", sync_workspace(agent_root))
            self.assertTrue((agent_root / "records" / "pending" / "manifest.yaml").is_file())

    def test_fresh_agent_workspace_allows_snapshot_to_create_pending_queue(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            initialized = subprocess.run(
                [str(INIT_WORKSPACE), str(root), "demo", "run-001", "application-metrics"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, initialized.returncode, initialized.stdout + initialized.stderr)
            workspace = Path(initialized.stdout.strip())
            pending = workspace / "records" / "pending"
            self.assertFalse(pending.exists())
            self.assertEqual(
                str(root / "scripts" / "workflow"),
                (workspace / "workflow").readlink().as_posix(),
            )
            self.assertEqual(
                str(root / "scripts" / "metrics_sync.py"),
                (workspace / "metrics-sync").readlink().as_posix(),
            )
            self.assertEqual(
                str(root / "scripts" / "metric_facts.py"),
                (workspace / "metric-facts").readlink().as_posix(),
            )
            self.assertEqual(
                str(root / "scripts" / "metrics_discovery.py"),
                (workspace / "metrics-discovery").readlink().as_posix(),
            )
            self.assertEqual(
                str(root / "scripts" / "metric_record.py"),
                (workspace / "metric-record").readlink().as_posix(),
            )
            self.assertEqual(
                str(root / "scripts" / "metric_queue.py"),
                (workspace / "metric-queue").readlink().as_posix(),
            )
            self.assertEqual(
                str(root / "scripts" / "prometheus_reader.py"),
                (workspace / "prometheus-reader").readlink().as_posix(),
            )
            self.assertEqual(
                str(root / "scripts" / "stage_check.py"),
                (workspace / "stage-check").readlink().as_posix(),
            )

            result = subprocess.run(
                [sys.executable, str(SNAPSHOT), "--output-dir", str(pending)],
                input="metric 1\n",
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertTrue((pending / "manifest.yaml").is_file())

    def test_metrics_reviewer_workspace_provides_the_deterministic_probe_wrapper(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            initialized = subprocess.run(
                [str(INIT_WORKSPACE), str(root), "demo", "run-001", "metrics-reviewer"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, initialized.returncode, initialized.stdout + initialized.stderr)
            workspace = Path(initialized.stdout.strip())
            self.assertEqual(
                str(root / "scripts" / "metrics_review_probes.py"),
                (workspace / "metrics-review-probes").readlink().as_posix(),
            )
            self.assertEqual(
                str(root / "scripts" / "metric_disposition.py"),
                (workspace / "metric-disposition").readlink().as_posix(),
            )

    def test_dashboard_architect_workspace_provides_capability_wrapper(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            initialized = subprocess.run(
                [str(INIT_WORKSPACE), str(root), "demo", "run-001", "dashboard-architect"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, initialized.returncode, initialized.stdout + initialized.stderr)
            workspace = Path(initialized.stdout.strip())
            self.assertEqual(
                str(root / "scripts" / "dashboard_capabilities.py"),
                (workspace / "dashboard-capabilities").readlink().as_posix(),
            )

    def test_promql_builder_workspace_provides_work_partition_wrapper(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            initialized = subprocess.run(
                [str(INIT_WORKSPACE), str(root), "demo", "run-001", "promql-builder"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, initialized.returncode, initialized.stdout + initialized.stderr)
            workspace = Path(initialized.stdout.strip())
            self.assertEqual(
                str(root / "scripts" / "query_work_partition.py"),
                (workspace / "query-work-partition").readlink().as_posix(),
            )

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
