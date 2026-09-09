from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "scripts"))

import metric_facts  # noqa: E402
import metric_disposition  # noqa: E402
import dashboard_capabilities  # noqa: E402
import metrics_discovery  # noqa: E402
import metrics_review_probes  # noqa: E402
import metric_record  # noqa: E402
import prometheus_probe_matrix  # noqa: E402
import promql_templates  # noqa: E402
import query_work_partition  # noqa: E402
import validate_workflow_artifact  # noqa: E402
from grafana_dry_run import replacement  # noqa: E402


class DeterministicStagesTest(unittest.TestCase):
    def test_new_dashboards_use_total_capacity_not_update_change_budget(self) -> None:
        limits = {
            "changed_questions": 12, "changed_panels": 12, "changed_queries": 24,
            "total_panels": 48, "total_queries": 64,
        }
        self.assertEqual(48, validate_workflow_artifact.change_limit(limits, "questions", True))
        self.assertEqual(48, validate_workflow_artifact.change_limit(limits, "panels", True))
        self.assertEqual(64, validate_workflow_artifact.change_limit(limits, "queries", True))
        self.assertEqual(12, validate_workflow_artifact.change_limit(limits, "questions", False))

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

    def test_query_work_partition_routes_only_typed_one_metric_rates_to_the_compiler(self) -> None:
        result = query_work_partition.partition(
            {"questions": [
                {"id": "Q001", "metric_ids": ["AM001"], "change": "NEW", "calculation": "rate",
                 "result_shape": "TIME_SERIES", "retained_labels": ["pod"]},
                {"id": "Q002", "metric_ids": ["AM001", "AM002"], "change": "NEW", "calculation": "ratio",
                 "result_shape": "TIME_SERIES", "retained_labels": ["pod"]},
                {"id": "Q003", "metric_ids": ["AM001"], "change": "PRESERVED", "calculation": "rate",
                 "result_shape": "TIME_SERIES", "retained_labels": ["pod"]},
            ]},
            {"approved": [
                {"id": "AM001", "family": "app_events_total", "type": "counter"},
                {"id": "AM002", "family": "app_errors_total", "type": "counter"},
            ]},
        )
        self.assertEqual("counter_rate_by_pod", result["standard"][0]["template"])
        self.assertEqual("MULTI_METRIC", result["custom"][0]["reason_code"])
        self.assertEqual("Q003", result["preserved"][0]["question_id"])

    def test_metric_facts_copies_observation_without_classification(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshots = root / "pending"
            snapshots.mkdir()
            (snapshots / "manifest.yaml").write_text(
                "kind: metric-snapshot-manifest\nfamily_count: 1\nschema_version: 1\nsource_ref: metrics\nline_count: 1\nparse_warnings: []\n",
                encoding="utf-8",
            )
            (snapshots / "F00001.yaml").write_text(
                "kind: metric-family-snapshot\nid: F00001\nfamily: demo_total\ndeclared_type: counter\nunit: null\nhelp: demo\nmembers: [demo_total]\nobserved_labels: [pod]\nsample_count: 1\nfirst_sample_line: 1\nlast_sample_line: 1\nhas_timestamps: false\nhas_exemplars: false\nsource_ref: metrics\nwarnings: []\nschema_version: 1\n",
                encoding="utf-8",
            )
            output = root / "facts.json"
            metric_facts.emit(snapshots, output)
            family = json.loads(output.read_text(encoding="utf-8"))["families"][0]
            self.assertEqual("NEEDS_AI", family["classification"])
            self.assertEqual("counter", family["declared_type"])
            metric_facts.emit(snapshots, output)

    def test_metric_facts_classifies_only_the_pinned_fastapi_identity_family(self) -> None:
        record = {
            "kind": "metric-family-snapshot", "id": "F00001", "family": "fastapi_app_info",
            "declared_type": "gauge", "unit": None, "help": "application identity", "members": ["fastapi_app_info"],
            "observed_labels": ["version"], "sample_count": 1, "has_timestamps": False,
            "has_exemplars": False, "source_ref": "metrics", "warnings": [],
        }
        fact = metric_facts.fact(record)
        self.assertEqual("PROCESS", fact["classification"])
        self.assertIn("identity", fact["classification_reason"])

        record["family"] = "grafana_build_info"
        record["members"] = ["grafana_build_info"]
        fact = metric_facts.fact(record)
        self.assertEqual("PROCESS", fact["classification"])
        self.assertEqual("build identity metadata", fact["classification_reason"])

    def test_metric_facts_classifies_only_verified_fastapi_server_workload(self) -> None:
        record = {
            "kind": "metric-family-snapshot", "id": "F00002", "family": "http_requests_total",
            "declared_type": "counter", "unit": None,
            "help": "Total number of requests by method, status and handler.",
            "members": ["http_requests_total"], "observed_labels": ["handler", "method", "status"],
            "sample_count": 1, "has_timestamps": False, "has_exemplars": False,
            "source_ref": "metrics", "warnings": [],
        }
        fact = metric_facts.fact(record)
        self.assertEqual("BUSINESS", fact["classification"])
        self.assertIn("server workload", fact["classification_reason"])

        record["declared_type"] = "gauge"
        self.assertEqual("NEEDS_AI", metric_facts.fact(record)["classification"])

    def test_metric_record_preserves_a_null_unit_without_yq_conditionals(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "records" / "pending").mkdir(parents=True)
            (root / "records" / "done").mkdir(parents=True)
            responses = root / "evidence" / "metric-discovery" / "responses"
            responses.mkdir(parents=True)
            (responses / "F00001.json").write_text(
                '{"status":"success","data":[{"kubernetes_namespace":"team-a","kubernetes_pod_name":"demo"}]}\n',
                encoding="utf-8",
            )
            (root / "state.yaml").write_text("pending: []\ncompleted: []\n", encoding="utf-8")
            (root / "records" / "pending" / "F00001.yaml").write_text(
                "kind: metric-family-snapshot\nid: F00001\nfamily: demo\ndeclared_type: gauge\nunit: null\nhelp: demo\nmembers: [demo]\nobserved_labels: []\nwarnings: []\n",
                encoding="utf-8",
            )
            previous = Path.cwd()
            try:
                os.chdir(root)
                output = metric_record.create("F00001.yaml", "BUSINESS")
            finally:
                os.chdir(previous)
            record = json.loads(subprocess.run(["yq", "eval", "-o=json", ".", str(output)], capture_output=True, text=True, check=True).stdout)
            self.assertEqual("M00001.yaml", output.name)
            self.assertIsNone(record["unit"])
            self.assertEqual("APPLICATION", record["source"])
            self.assertEqual(["kubernetes_namespace", "kubernetes_pod_name"], record["stored_labels"])
            self.assertEqual(
                ["evidence/metric-facts.json", "evidence/metric-discovery/responses/F00001.json"],
                record["evidence_refs"],
            )

            (root / "records" / "pending" / "F00002.yaml").write_text(
                "kind: metric-family-snapshot\nid: F00002\nfamily: fastapi_app_info\ndeclared_type: gauge\nunit: null\nhelp: identity\nmembers: [fastapi_app_info]\nobserved_labels: []\nwarnings: []\n",
                encoding="utf-8",
            )
            try:
                os.chdir(root)
                with self.assertRaisesRegex(metric_record.RecordError, "pinned family category is PROCESS"):
                    metric_record.create("F00002.yaml", "BUSINESS")
            finally:
                os.chdir(previous)

    def test_metrics_discovery_probes_every_snapshot_and_summarizes_candidates(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshots = root / "pending"
            snapshots.mkdir()
            for identifier, family in (("F00001", "idle_metric"), ("F00002", "active_metric")):
                (snapshots / f"{identifier}.yaml").write_text(
                    f"kind: metric-family-snapshot\nid: {identifier}\nfamily: {family}\n",
                    encoding="utf-8",
                )
            requests: list[dict[str, object]] = []

            def fetch(request: dict[str, object]) -> bytes:
                requests.append(request)
                if request["params"]["match[]"] == "active_metric":
                    return b'{"status":"success","data":[{"kubernetes_namespace":"team-a","app":"demo"}]}'
                return b'{"status":"success","data":[]}'

            summary = metrics_discovery.discover(snapshots, root / "discovery", fetch)
            self.assertEqual(["idle_metric", "active_metric"], [item["params"]["match[]"] for item in requests])
            self.assertEqual("EMPTY", summary["families"][0]["result"])
            self.assertEqual(["team-a"], summary["families"][1]["namespace_candidates"])
            self.assertEqual(["kubernetes_namespace"], summary["families"][1]["namespace_label_keys"])
            self.assertEqual(["team-a"], summary["namespace_candidates"])
            self.assertTrue((root / "discovery" / "responses" / "F00002.json").is_file())

            resumed = metrics_discovery.discover(
                snapshots, root / "discovery", lambda _: self.fail("completed discovery was re-run"),
            )
            self.assertEqual(summary, resumed)

    def test_metrics_review_probes_uses_the_bound_namespace_and_stable_evidence_path(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            requests: list[dict[str, object]] = []

            def fetch(request: dict[str, object]) -> bytes:
                requests.append(request)
                return b'{"status":"success","data":[{"namespace":"team-a","pod":"demo"}]}'

            summary = metrics_review_probes.probe(
                [{"id": "K002", "source": "KUBELET", "family": "container_memory_working_set_bytes"}],
                ["team-a"], root / "probes", fetch,
            )
            self.assertEqual(
                'container_memory_working_set_bytes{namespace=~"^(?:team\\-a)$"}',
                requests[0]["params"]["match[]"],
            )
            self.assertEqual("SERIES", summary["probes"][0]["result"])
            self.assertTrue((root / "probes" / "responses" / "K002.json").is_file())
            self.assertEqual(
                summary,
                metrics_review_probes.probe(
                    [{"id": "K002", "source": "KUBELET", "family": "container_memory_working_set_bytes"}],
                    ["team-a"], root / "probes", lambda _: self.fail("completed probe evidence was re-run"),
                ),
            )

    def test_metric_disposition_rejects_unknown_ids_and_writes_stable_records(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            available = {("kubernetes-metrics", "I002"), ("kubernetes-metrics", "I003")}
            records = metric_disposition.write_records(
                root, available, "rejected", "kubernetes-metrics", ["I002", "I003"],
                "NO_TARGET_SERIES", "No series were observed.",
            )
            self.assertEqual(2, len(records))
            self.assertTrue((root / "records" / "rejected" / "kubernetes-metrics-I002.yaml").is_file())
            with self.assertRaisesRegex(metric_disposition.DispositionError, "ticketed shortlist"):
                metric_disposition.write_records(
                    root, available, "rejected", "kubernetes-metrics", ["I004"],
                    "NO_TARGET_SERIES", "No series were observed.",
                )

    def test_dashboard_capabilities_projects_only_planning_fields(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            contract = root / "metrics-contract.yaml"
            contract.write_text(
                "approved:\n"
                "  - id: AM001\n    source_artifact: application-metrics\n    source_metric_id: M001\n"
                "    source: APPLICATION\n    category: BUSINESS\n    family: app_events_total\n"
                "    type: counter\n    unit: null\n    semantics: events\n    lifecycle: process\n"
                "    identity_labels: [pod]\n    bounded_dimensions: [result]\n"
                "    availability: VERIFIED\n    allowed_use: PLAN\n    risks: []\n",
                encoding="utf-8",
            )
            output = root / "approved-capabilities.json"
            summary = dashboard_capabilities.emit(contract, output)
            self.assertEqual(1, summary["totals"]["plan"])
            self.assertEqual("AM001", summary["capabilities"][0]["id"])
            self.assertNotIn("evidence_refs", summary["capabilities"][0])
            self.assertEqual(summary, dashboard_capabilities.emit(contract, output))

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
