from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "scripts"))

import metric_facts  # noqa: E402
import prometheus_probe_matrix  # noqa: E402
import promql_templates  # noqa: E402
from grafana_dry_run import replacement  # noqa: E402


class DeterministicStagesTest(unittest.TestCase):
    def test_counter_template_requires_declared_counter_and_compiles_stably(self) -> None:
        result = promql_templates.compile_template({
            "template": "counter_rate_by_pod",
            "metric": "http_requests_total",
            "metric_type": "counter",
            "selector": 'namespace="$namespace",pod=~"${pod:regex}"',
            "window": "$__rate_interval",
        })
        self.assertEqual(
            'sum by (pod) (rate(http_requests_total{namespace="$namespace",pod=~"${pod:regex}"}[$__rate_interval]))',
            result["expression"],
        )
        with self.assertRaisesRegex(promql_templates.TemplateError, "counter"):
            promql_templates.compile_template({
                "template": "counter_rate_by_pod", "metric": "looks_total", "metric_type": "gauge", "window": "5m",
            })

    def test_metric_facts_copies_observation_without_classification(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshots = root / "pending"
            snapshots.mkdir()
            (snapshots / "manifest.yaml").write_text(
                "kind: metric-snapshot-manifest\nfamily_count: 1\nschema_version: 1\nsource_ref: metrics\nline_count: 1\nparse_warnings: []\n",
                encoding="utf-8",
            )
            (snapshots / "00001.yaml").write_text(
                "kind: metric-family-snapshot\nid: F00001\nfamily: demo_total\ndeclared_type: counter\nunit: null\nhelp: demo\nmembers: [demo_total]\nobserved_labels: [pod]\nsample_count: 1\nfirst_sample_line: 1\nlast_sample_line: 1\nhas_timestamps: false\nhas_exemplars: false\nsource_ref: metrics\nwarnings: []\nschema_version: 1\n",
                encoding="utf-8",
            )
            output = root / "facts.json"
            metric_facts.emit(snapshots, output)
            family = json.loads(output.read_text(encoding="utf-8"))["families"][0]
            self.assertEqual("NEEDS_AI", family["classification"])
            self.assertEqual("counter", family["declared_type"])

    def test_probe_inspection_rejects_duplicate_declared_identity(self) -> None:
        payload = json.dumps({"status": "success", "data": {"result": [
            {"metric": {"pod": "a", "instance": "one"}},
            {"metric": {"pod": "a", "instance": "two"}},
        ]}}).encode()
        with self.assertRaisesRegex(prometheus_probe_matrix.ProbeError, "duplicate"):
            prometheus_probe_matrix.inspect({"id": "one", "identity_labels": ["pod"]}, payload)

    def test_update_envelope_preserves_live_metadata_and_replaces_only_spec(self) -> None:
        with TemporaryDirectory() as temporary:
            request = Path(temporary) / "request.json"
            name = replacement(
                {"apiVersion": "dashboard.grafana.app/v2", "kind": "Dashboard", "metadata": {"name": "demo"}, "spec": {"title": "new"}},
                json.dumps({"metadata": {"name": "demo", "resourceVersion": "7", "annotations": {"grafana.app/folder": "ops"}}, "spec": {"title": "old"}}).encode(),
                request,
            )
            body = json.loads(request.read_text(encoding="utf-8"))
            self.assertEqual("demo", name)
            self.assertEqual("7", body["metadata"]["resourceVersion"])
            self.assertEqual({"title": "new"}, body["spec"])


if __name__ == "__main__":
    unittest.main()
