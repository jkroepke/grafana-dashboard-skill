from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]
VALIDATOR = REPOSITORY / "scripts" / "validate_workflow_artifact.py"
PARITY = REPOSITORY / "scripts" / "verify_query_parity.py"
CHAIN = REPOSITORY / "scripts" / "verify_workflow_chain.py"
DASHBOARD_CONTRACT = REPOSITORY / "scripts" / "verify_dashboard_contract.py"
DASHBOARD_INTEGRITY = REPOSITORY / "scripts" / "dashboard_integrity.py"
NON_PROMETHEUS = REPOSITORY / "scripts" / "verify_non_prometheus_preservation.py"
RENDER_VERIFIER = REPOSITORY / "scripts" / "verify_candidate_render.py"
INIT_WORKSPACE = REPOSITORY / "scripts" / "init_agent_workspace.sh"
VALIDATE_WORKSPACE = REPOSITORY / "scripts" / "validate_agent_workspace.sh"
CREATE_COORDINATOR_ARTIFACT = REPOSITORY / "scripts" / "create_coordinator_artifact.py"
COORDINATOR_STAGE = REPOSITORY / "scripts" / "coordinator_stage.py"
STAGE_CHECK = REPOSITORY / "scripts" / "stage_check.py"
KUBERNETES_PRESETS = REPOSITORY / "scripts" / "kubernetes_presets.py"


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def load_artifact(path: Path) -> dict:
    result = subprocess.run(
        ["yq", "eval", "-o=json", ".", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(result.stdout + result.stderr)
    return json.loads(result.stdout)


class WorkflowScriptsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.paths: dict[str, Path] = {}
        self._write_valid_pipeline()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write(self, name: str, value: object) -> Path:
        is_artifact = isinstance(value, dict) and "artifact_type" in value
        path = self.root / f"{name}.{'yaml' if is_artifact else 'json'}"
        if is_artifact:
            result = subprocess.run(
                ["yq", "eval", "-p=json", "-o=yaml", "."],
                input=json.dumps(value, sort_keys=True),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            path.write_text(result.stdout, encoding="utf-8")
        else:
            path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        self.paths[name] = path
        return path

    def envelope(self, artifact_type: str, status: str, inputs: dict[str, str], **fields: object) -> dict:
        return {
            "schema_version": 1,
            "artifact_type": artifact_type,
            "run_id": "test-run",
            "revision": 1,
            "inputs": inputs,
            "status": status,
            **fields,
        }

    def run_tool(self, *arguments: object, expected: int = 0) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [sys.executable, *(str(argument) for argument in arguments)],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(expected, result.returncode, result.stdout + result.stderr)
        return result

    def validate(self, name: str, inputs: dict[str, str]) -> subprocess.CompletedProcess[str]:
        arguments: list[object] = [VALIDATOR, self.paths[name]]
        for artifact_type, input_name in inputs.items():
            arguments.extend(["--input", f"{artifact_type}={self.paths[input_name]}"])
        arguments.extend(self.support_arguments(set(inputs)))
        return self.run_tool(*arguments)

    def support_arguments(self, direct_names: set[str]) -> list[object]:
        required: set[str] = set()
        visited: set[str] = set()

        def visit(name: str) -> None:
            if name in visited:
                return
            visited.add(name)
            artifact_value = load_artifact(self.paths[name])
            for dependency in artifact_value["inputs"]:
                if dependency not in direct_names:
                    required.add(dependency)
                visit(dependency)

        for direct_name in direct_names:
            visit(direct_name)
        arguments: list[object] = []
        for name in sorted(required):
            arguments.extend(["--support", f"{name}={self.paths[name]}"])
        return arguments

    def _write_valid_pipeline(self) -> None:
        (self.root / "metrics.ndjson").write_text("{}\n", encoding="utf-8")
        (self.root / "publish-evidence.json").write_text("{}\n", encoding="utf-8")
        final_source = self.root / "dashboard.jsonnet"
        candidate_source = self.root / "dashboard.candidate.jsonnet"
        workspace = self.root / "dashboards" / "test-project" / "workspace"
        workspace.mkdir(parents=True)
        rendered = workspace / "dashboard-builder" / "test-run" / "evidence" / "rendered.json"
        rendered.parent.mkdir(parents=True)
        self.rendered_path = rendered
        candidate_source.write_text("{ candidate: true }\n", encoding="utf-8")

        limits = {
            "approved_metrics": 4,
            "changed_questions": 4,
            "changed_panels": 4,
            "changed_queries": 8,
            "total_panels": 8,
            "total_queries": 16,
            "findings": 8,
        }
        run = self.envelope(
            "run-contract",
            "PASS",
            {},
            repository_root=str(self.root),
            workspace=str(workspace),
            source={
                "final_path": str(final_source),
                "candidate_path": str(candidate_source),
                "baseline_state": "ABSENT",
                "baseline_sha256": None,
            },
            rendered_candidate_path=str(rendered),
            render={
                "cwd": str(self.root),
                "argv": [
                    sys.executable,
                    "-c",
                    "import pathlib,sys;sys.stdout.buffer.write(pathlib.Path(sys.argv[1]).read_bytes())",
                    "{source}",
                ],
                "timeout_seconds": 30,
            },
            schema={"dashboard": "V2", "grafana_version": "13", "grafonnet_revision": "test"},
            limits=limits,
            capabilities={
                "datasource_access": False,
                "dashboard_api_validation": False,
                "publish_requested": False,
            },
            selector_proposals={},
        )
        self.write("run-contract", run)
        namespace_scope = self.root / "application-namespace-scope.yaml"
        namespace_scope.write_text(
            "schema_version: 1\nnamespaces:\n  - team-a\n  - team-b\n",
            encoding="utf-8",
        )

        metric = {
            "id": "M001",
            "source": "APPLICATION",
            "category": "BUSINESS",
            "family": "work_total",
            "members": ["work_total"],
            "type": "counter",
            "unit": None,
            "help": "Completed work.",
            "observed_labels": ["outcome"],
            "stored_labels": ["kubernetes_namespace", "kubernetes_pod_name"],
            "match_keys": [],
            "population": "application pods",
            "lifecycle": "process lifetime",
            "availability": "OBSERVED",
            "cardinality_risk": "LOW",
            "evidence_refs": ["metrics.ndjson:1"],
            "limitations": [],
        }
        app = self.envelope(
            "application-metrics",
            "DONE",
            {"run-contract": digest(self.paths["run-contract"])},
            catalog_ref="metrics.ndjson",
            metrics=[metric],
            omission_counts={},
            namespace_scope={
                "evidence_ref": str(namespace_scope),
                "sha256": digest(namespace_scope),
                "namespace_count": 2,
            },
        )
        self.write("application-metrics", app)

        kubernetes = self.envelope(
            "kubernetes-metrics",
            "DONE",
            {
                "run-contract": digest(self.paths["run-contract"]),
                "application-metrics": digest(self.paths["application-metrics"]),
            },
            catalog_ref="metrics.ndjson",
            metrics=[],
            omission_counts={},
            namespace_scope_ref=str(namespace_scope),
            namespace_scope_sha256=digest(namespace_scope),
        )
        self.write("kubernetes-metrics", kubernetes)

        approved = {
            "id": "AM001",
            "source_artifact": "application-metrics",
            "source_metric_id": "M001",
            "source": "APPLICATION",
            "category": "BUSINESS",
            "family": "work_total",
            "type": "counter",
            "unit": None,
            "semantics": "Completed work by outcome.",
            "lifecycle": "process lifetime",
            "label_layer": "APPLICATION_STORED",
            "identity_labels": ["kubernetes_namespace", "kubernetes_pod_name"],
            "bounded_dimensions": ["outcome"],
            "availability": "VERIFIED",
            "allowed_use": "PLAN",
            "risks": [],
            "evidence_refs": ["metrics.ndjson:1"],
        }
        metrics = self.envelope(
            "metrics-contract",
            "PASS",
            {
                "run-contract": digest(self.paths["run-contract"]),
                "application-metrics": digest(self.paths["application-metrics"]),
            },
            approved=[approved],
            rejected=[],
            not_considered=[],
            selector_contract={
                "application_namespace_label": "kubernetes_namespace",
                "application_pod_label": "kubernetes_pod_name",
                "kubernetes_namespace_label": None,
                "kubernetes_pod_label": None,
                "istio_source_namespace_label": None,
                "istio_destination_namespace_label": None,
                "cluster_label": None,
                "fixed_selector_refs": [],
                "population_notes": ["application pods"],
                "scrape_interval_ref": None,
            },
            unresolved=[],
        )
        self.write("metrics-contract", metrics)

        plan = self.envelope(
            "dashboard-plan",
            "PASS",
            {
                "run-contract": digest(self.paths["run-contract"]),
                "metrics-contract": digest(self.paths["metrics-contract"]),
            },
            panel_groups=[{"id": "G001", "title": "Overview", "placement": "OVERVIEW", "order": 0}],
            questions=[{
                "id": "Q001",
                "text": "How much work completes?",
                "priority": "MUST",
                "category": "BUSINESS",
                "metric_ids": ["AM001"],
                "calculation": "rate",
                "result_shape": "TIME_SERIES",
                "retained_labels": ["outcome"],
                "no_data_requirement": "Show missing data as unknown.",
                "change": "NEW",
            }],
            panels=[{
                "id": "P001",
                "question_ids": ["Q001"],
                "group_id": "G001",
                "visualization": "time series",
                "placement": "OVERVIEW",
                "size": "WIDE",
                "change": "NEW",
            }],
            required_consumers=[
                {
                    "id": "V_NAMESPACE",
                    "role": "VARIABLE",
                    "rendered_name": "namespace",
                    "purpose": "Select namespace.",
                    "metric_ids": ["AM001"],
                },
                {
                    "id": "V_POD",
                    "role": "VARIABLE",
                    "rendered_name": "pod",
                    "purpose": "Select pods.",
                    "metric_ids": ["AM001"],
                },
            ],
            omissions=[],
            budgets=limits,
        )
        self.write("dashboard-plan", plan)

        editor_ref = "PrometheusVariableQueryEditor-VariableQuery"
        queries = [
            {
                "id": "T001",
                "role": "PANEL",
                "consumer_id": "P001",
                "consumer_locator": {"kind": "PANEL", "name": "P001", "ref_id": "A"},
                "plugin_query_model": None,
                "question_id": "Q001",
                "metric_ids": ["AM001"],
                "language": "PROMQL",
                "expression": "sum(rate(work_total[$__rate_interval]))",
                "mode": "RANGE",
                "datasource_ref": "${datasource}",
                "unit": "ops",
                "result_identity": [],
                "no_data_semantics": "No observed series.",
                "expected_cardinality": "One series.",
                "assumptions": [],
                "edge_cases": [],
                "change": "NEW",
                "validation": {"static": "PASS", "live": "UNVERIFIED", "evidence_refs": []},
            },
            {
                "id": "T002",
                "role": "VARIABLE",
                "consumer_id": "V_NAMESPACE",
                "consumer_locator": {"kind": "VARIABLE", "name": "namespace", "ref_id": editor_ref},
                "plugin_query_model": {"qry_type": 1, "editor_ref_id": editor_ref},
                "question_id": None,
                "metric_ids": ["AM001"],
                "language": "PROMETHEUS_VARIABLE",
                "expression": "label_values(work_total, kubernetes_namespace)",
                "mode": "VARIABLE",
                "datasource_ref": "${datasource}",
                "unit": None,
                "result_identity": ["kubernetes_namespace"],
                "no_data_semantics": "No namespace options.",
                "expected_cardinality": "Bounded namespaces.",
                "assumptions": [],
                "edge_cases": [],
                "change": "NEW",
                "validation": {"static": "PASS", "live": "UNVERIFIED", "evidence_refs": []},
            },
            {
                "id": "T003",
                "role": "VARIABLE",
                "consumer_id": "V_POD",
                "consumer_locator": {"kind": "VARIABLE", "name": "pod", "ref_id": editor_ref},
                "plugin_query_model": {"qry_type": 1, "editor_ref_id": editor_ref},
                "question_id": None,
                "metric_ids": ["AM001"],
                "language": "PROMETHEUS_VARIABLE",
                "expression": "label_values(work_total{kubernetes_namespace=\"$namespace\"}, kubernetes_pod_name)",
                "mode": "VARIABLE",
                "datasource_ref": "${datasource}",
                "unit": None,
                "result_identity": ["kubernetes_pod_name"],
                "no_data_semantics": "No pod options.",
                "expected_cardinality": "Application pods.",
                "assumptions": [],
                "edge_cases": [],
                "change": "NEW",
                "validation": {"static": "PASS", "live": "UNVERIFIED", "evidence_refs": []},
            },
        ]
        pack = self.envelope(
            "query-pack",
            "PASS",
            {
                "run-contract": digest(self.paths["run-contract"]),
                "metrics-contract": digest(self.paths["metrics-contract"]),
                "dashboard-plan": digest(self.paths["dashboard-plan"]),
            },
            queries=queries,
            live_validation="UNVERIFIED",
        )
        self.write("query-pack", pack)

        query_review = self.envelope(
            "query-review",
            "PASS",
            {
                "run-contract": digest(self.paths["run-contract"]),
                "metrics-contract": digest(self.paths["metrics-contract"]),
                "dashboard-plan": digest(self.paths["dashboard-plan"]),
                "query-pack": digest(self.paths["query-pack"]),
            },
            query_pack_sha256=digest(self.paths["query-pack"]),
            query_count=3,
            live_validation="UNVERIFIED",
            findings=[],
        )
        self.write("query-review", query_review)

        rendered_value = {
            "apiVersion": "dashboard.grafana.app/v2",
            "kind": "Dashboard",
            "spec": {
                "elements": {
                    "P001": {
                        "kind": "Panel",
                        "spec": {
                            "data": {
                                "kind": "QueryGroup",
                                "spec": {
                                    "queries": [{
                                        "kind": "PanelQuery",
                                        "spec": {
                                            "refId": "A",
                                            "query": {
                                                "kind": "DataQuery",
                                                "group": "prometheus",
                                                "datasource": {"name": "${datasource}"},
                                                "spec": {"expr": queries[0]["expression"]},
                                            },
                                        },
                                    }]
                                },
                            }
                        },
                    }
                },
                "variables": [
                    {
                        "kind": "DatasourceVariable",
                        "spec": {
                            "name": "datasource",
                            "pluginId": "prometheus",
                            "multi": False,
                            "includeAll": False,
                        },
                    },
                    {
                        "kind": "QueryVariable",
                        "spec": {
                            "name": "namespace",
                            "multi": False,
                            "includeAll": False,
                            "query": {
                                "kind": "DataQuery",
                                "group": "prometheus",
                                "datasource": {"name": "${datasource}"},
                                "spec": {
                                    "qryType": 1,
                                    "query": queries[1]["expression"],
                                    "refId": editor_ref,
                                },
                            },
                        },
                    },
                    {
                        "kind": "QueryVariable",
                        "spec": {
                            "name": "pod",
                            "multi": True,
                            "includeAll": True,
                            "allValue": "",
                            "query": {
                                "kind": "DataQuery",
                                "group": "prometheus",
                                "datasource": {"name": "${datasource}"},
                                "spec": {
                                    "qryType": 1,
                                    "query": queries[2]["expression"],
                                    "refId": editor_ref,
                                },
                            },
                        },
                    },
                ],
                "annotations": [],
            }
        }
        rendered_json = json.dumps(rendered_value)
        rendered.write_text(rendered_json, encoding="utf-8")
        candidate_source.write_text(rendered_json, encoding="utf-8")

        build = self.envelope(
            "dashboard-build",
            "PASS",
            {
                "run-contract": digest(self.paths["run-contract"]),
                "metrics-contract": digest(self.paths["metrics-contract"]),
                "dashboard-plan": digest(self.paths["dashboard-plan"]),
                "query-pack": digest(self.paths["query-pack"]),
                "query-review": digest(self.paths["query-review"]),
            },
            candidate_path=str(candidate_source),
            candidate_sha256=digest(candidate_source),
            rendered_path=str(rendered),
            rendered_sha256=digest(rendered),
            query_pack_sha256=digest(self.paths["query-pack"]),
            query_review_sha256=digest(self.paths["query-review"]),
            baseline_state="ABSENT",
            baseline_sha256=None,
            integrated_query_ids=["T001", "T002", "T003"],
            checks={
                "format": "PASS",
                "render": "PASS",
                "json": "PASS",
                "query_parity": "PASS",
                "local_schema": "UNVERIFIED",
                "layout_references": "PASS",
                "variable_payloads": "PASS",
            },
            findings=[],
        )
        self.write("dashboard-build", build)

        dashboard_review = self.envelope(
            "dashboard-review",
            "PASS",
            {
                "run-contract": digest(self.paths["run-contract"]),
                "dashboard-plan": digest(self.paths["dashboard-plan"]),
                "query-pack": digest(self.paths["query-pack"]),
                "query-review": digest(self.paths["query-review"]),
                "dashboard-build": digest(self.paths["dashboard-build"]),
            },
            build_manifest_sha256=digest(self.paths["dashboard-build"]),
            candidate_sha256=digest(candidate_source),
            rendered_sha256=digest(rendered),
            query_pack_sha256=digest(self.paths["query-pack"]),
            query_review_sha256=digest(self.paths["query-review"]),
            query_parity="PASS",
            target_dry_run="NOT_CONFIGURED",
            findings=[],
        )
        self.write("dashboard-review", dashboard_review)

    def test_valid_artifacts_parity_chain_and_promotion(self) -> None:
        self.validate("run-contract", {})
        self.validate("application-metrics", {"run-contract": "run-contract"})
        self.validate("kubernetes-metrics", {
            "run-contract": "run-contract",
            "application-metrics": "application-metrics",
        })
        self.validate("metrics-contract", {
            "run-contract": "run-contract",
            "application-metrics": "application-metrics",
        })
        self.validate("dashboard-plan", {
            "run-contract": "run-contract",
            "metrics-contract": "metrics-contract",
        })
        self.validate("query-pack", {
            "run-contract": "run-contract",
            "metrics-contract": "metrics-contract",
            "dashboard-plan": "dashboard-plan",
        })
        self.validate("query-review", {
            "run-contract": "run-contract",
            "metrics-contract": "metrics-contract",
            "dashboard-plan": "dashboard-plan",
            "query-pack": "query-pack",
        })
        self.validate("dashboard-build", {
            "run-contract": "run-contract",
            "metrics-contract": "metrics-contract",
            "dashboard-plan": "dashboard-plan",
            "query-pack": "query-pack",
            "query-review": "query-review",
        })
        self.validate("dashboard-review", {
            "run-contract": "run-contract",
            "dashboard-plan": "dashboard-plan",
            "query-pack": "query-pack",
            "query-review": "query-review",
            "dashboard-build": "dashboard-build",
        })
        self.run_tool(PARITY, self.paths["query-pack"], self.paths["query-review"], self.rendered_path)
        chain_arguments = [
            CHAIN,
            self.paths["run-contract"],
            self.paths["metrics-contract"],
            self.paths["dashboard-plan"],
            self.paths["query-pack"],
            self.paths["query-review"],
            self.paths["dashboard-build"],
            self.paths["dashboard-review"],
            "--application-metrics",
            self.paths["application-metrics"],
        ]
        self.run_tool(*chain_arguments)
        self.run_tool(*chain_arguments, "--promote")
        self.assertTrue((self.root / "dashboard.jsonnet").is_file())
        self.assertFalse((self.root / "dashboard.candidate.jsonnet").exists())
        self.validate("dashboard-build", {
            "run-contract": "run-contract",
            "metrics-contract": "metrics-contract",
            "dashboard-plan": "dashboard-plan",
            "query-pack": "query-pack",
            "query-review": "query-review",
        })
        self.validate("dashboard-review", {
            "run-contract": "run-contract",
            "dashboard-plan": "dashboard-plan",
            "query-pack": "query-pack",
            "query-review": "query-review",
            "dashboard-build": "dashboard-build",
        })

    def test_closed_plan_rejects_hidden_query_payload(self) -> None:
        plan = load_artifact(self.paths["dashboard-plan"])
        plan["payload"] = "rate(fake_total[5m])"
        self.write("bad-plan", plan)
        result = self.run_tool(
            VALIDATOR,
            self.paths["bad-plan"],
            "--input",
            f"run-contract={self.paths['run-contract']}",
            "--input",
            f"metrics-contract={self.paths['metrics-contract']}",
            *self.support_arguments({"run-contract", "metrics-contract"}),
            expected=1,
        )
        self.assertIn("extra=['payload']", result.stderr)

    def test_pass_review_with_finding_is_rejected(self) -> None:
        review = load_artifact(self.paths["query-review"])
        review["findings"] = [{
            "query_id": "T001",
            "code": "BAD_RATE",
            "evidence_ref": None,
            "required_change": "Correct the rate semantics.",
        }]
        self.write("bad-review", review)
        result = self.run_tool(
            VALIDATOR,
            self.paths["bad-review"],
            "--input",
            f"run-contract={self.paths['run-contract']}",
            "--input",
            f"metrics-contract={self.paths['metrics-contract']}",
            "--input",
            f"dashboard-plan={self.paths['dashboard-plan']}",
            "--input",
            f"query-pack={self.paths['query-pack']}",
            *self.support_arguments({
                "run-contract", "metrics-contract", "dashboard-plan", "query-pack"
            }),
            expected=1,
        )
        self.assertIn("zero findings", result.stderr)

    def test_plan_rejects_orphaned_question(self) -> None:
        plan = load_artifact(self.paths["dashboard-plan"])
        orphan = copy.deepcopy(plan["questions"][0])
        orphan["id"] = "Q002"
        orphan["text"] = "Which planned question was not assigned?"
        plan["questions"].append(orphan)
        self.write("orphan-plan", plan)
        result = self.run_tool(
            VALIDATOR,
            self.paths["orphan-plan"],
            "--input",
            f"run-contract={self.paths['run-contract']}",
            "--input",
            f"metrics-contract={self.paths['metrics-contract']}",
            *self.support_arguments({"run-contract", "metrics-contract"}),
            expected=1,
        )
        self.assertIn("every planned question must be assigned", result.stderr)

    def test_plan_rejects_queryless_datasource_as_a_prometheus_consumer(self) -> None:
        plan = load_artifact(self.paths["dashboard-plan"])
        plan["required_consumers"].append({
            "id": "V_DATASOURCE",
            "role": "VARIABLE",
            "rendered_name": "datasource",
            "purpose": "Select the Prometheus datasource.",
            "metric_ids": ["AM001"],
        })
        self.write("datasource-consumer-plan", plan)
        result = self.run_tool(
            VALIDATOR,
            self.paths["datasource-consumer-plan"],
            "--input",
            f"run-contract={self.paths['run-contract']}",
            "--input",
            f"metrics-contract={self.paths['metrics-contract']}",
            *self.support_arguments({"run-contract", "metrics-contract"}),
            expected=1,
        )
        self.assertIn("queryless DatasourceVariable", result.stderr)

    def test_query_pack_rejects_literal_datasource(self) -> None:
        pack = load_artifact(self.paths["query-pack"])
        pack["queries"][0]["datasource_ref"] = "literal-datasource-uid"
        self.write("literal-datasource-pack", pack)
        result = self.run_tool(
            VALIDATOR,
            self.paths["literal-datasource-pack"],
            "--input",
            f"run-contract={self.paths['run-contract']}",
            "--input",
            f"metrics-contract={self.paths['metrics-contract']}",
            "--input",
            f"dashboard-plan={self.paths['dashboard-plan']}",
            *self.support_arguments({"run-contract", "metrics-contract", "dashboard-plan"}),
            expected=1,
        )
        self.assertIn("datasource_ref must be ${datasource}", result.stderr)

    def test_total_suffix_does_not_override_declared_gauge(self) -> None:
        app = load_artifact(self.paths["application-metrics"])
        source_metric = app["metrics"][0]
        source_metric["family"] = "http_requests_total"
        source_metric["members"] = ["http_requests_total"]
        source_metric["type"] = "gauge"
        gauge_app = self.write("gauge-application-metrics", app)

        metrics = load_artifact(self.paths["metrics-contract"])
        metrics["inputs"]["application-metrics"] = digest(gauge_app)
        approved = metrics["approved"][0]
        approved["family"] = "http_requests_total"
        approved["type"] = "gauge"
        gauge_metrics = self.write("gauge-metrics-contract", metrics)

        plan = load_artifact(self.paths["dashboard-plan"])
        plan["inputs"]["metrics-contract"] = digest(gauge_metrics)
        gauge_plan = self.write("gauge-dashboard-plan", plan)

        pack = load_artifact(self.paths["query-pack"])
        pack["inputs"]["metrics-contract"] = digest(gauge_metrics)
        pack["inputs"]["dashboard-plan"] = digest(gauge_plan)
        for query in pack["queries"]:
            query["expression"] = query["expression"].replace("work_total", "http_requests_total")
        gauge_pack = self.write("gauge-query-pack", pack)

        result = self.run_tool(
            VALIDATOR,
            gauge_pack,
            "--input",
            f"run-contract={self.paths['run-contract']}",
            "--input",
            f"metrics-contract={gauge_metrics}",
            "--input",
            f"dashboard-plan={gauge_plan}",
            "--support",
            f"application-metrics={gauge_app}",
            expected=1,
        )
        self.assertIn("counter-only function but no referenced metric has a counter-compatible type", result.stderr)

    def test_revision_four_is_rejected(self) -> None:
        plan = load_artifact(self.paths["dashboard-plan"])
        plan["revision"] = 4
        self.write("revision-four-plan", plan)
        result = self.run_tool(
            VALIDATOR,
            self.paths["revision-four-plan"],
            "--input",
            f"run-contract={self.paths['run-contract']}",
            "--input",
            f"metrics-contract={self.paths['metrics-contract']}",
            *self.support_arguments({"run-contract", "metrics-contract"}),
            expected=1,
        )
        self.assertIn("revision must be <= 3", result.stderr)

    def test_new_dashboard_rejects_preserved_change_label(self) -> None:
        plan = load_artifact(self.paths["dashboard-plan"])
        plan["questions"][0]["change"] = "PRESERVED"
        self.write("false-preserved-plan", plan)
        result = self.run_tool(
            VALIDATOR,
            self.paths["false-preserved-plan"],
            "--input",
            f"run-contract={self.paths['run-contract']}",
            "--input",
            f"metrics-contract={self.paths['metrics-contract']}",
            *self.support_arguments({"run-contract", "metrics-contract"}),
            expected=1,
        )
        self.assertIn("must be NEW without a baseline", result.stderr)

    def test_metrics_contract_rejects_invented_label(self) -> None:
        metrics = load_artifact(self.paths["metrics-contract"])
        metrics["approved"][0]["identity_labels"].append("invented_label")
        self.write("invented-label-metrics", metrics)
        result = self.run_tool(
            VALIDATOR,
            self.paths["invented-label-metrics"],
            "--input",
            f"run-contract={self.paths['run-contract']}",
            "--input",
            f"application-metrics={self.paths['application-metrics']}",
            expected=1,
        )
        self.assertIn("introduces labels absent", result.stderr)

    def test_downstream_validation_recursively_rejects_invalid_input_body(self) -> None:
        plan = load_artifact(self.paths["dashboard-plan"])
        plan["hidden"] = "invalid"
        invalid_plan = self.write("invalid-upstream-plan", plan)
        pack = load_artifact(self.paths["query-pack"])
        pack["inputs"]["dashboard-plan"] = digest(invalid_plan)
        downstream = self.write("downstream-pack", pack)
        result = self.run_tool(
            VALIDATOR,
            downstream,
            "--input",
            f"run-contract={self.paths['run-contract']}",
            "--input",
            f"metrics-contract={self.paths['metrics-contract']}",
            "--input",
            f"dashboard-plan={invalid_plan}",
            "--support",
            f"application-metrics={self.paths['application-metrics']}",
            expected=1,
        )
        self.assertIn("extra=['hidden']", result.stderr)

    def test_run_contract_confines_source_to_repository(self) -> None:
        run = load_artifact(self.paths["run-contract"])
        outside = self.root.parent / "outside-dashboard.jsonnet"
        run["source"]["final_path"] = str(outside)
        run["source"]["candidate_path"] = str(self.root.parent / "outside-dashboard.candidate.jsonnet")
        self.write("outside-run", run)
        result = self.run_tool(VALIDATOR, self.paths["outside-run"], expected=1)
        self.assertIn("inside repository_root", result.stderr)

    def test_run_contract_rejects_classic_dashboard_schema(self) -> None:
        run = load_artifact(self.paths["run-contract"])
        run["schema"]["dashboard"] = "CLASSIC"
        self.write("classic-run", run)
        result = self.run_tool(VALIDATOR, self.paths["classic-run"], expected=1)
        self.assertIn("Dashboard Schema V2 only", result.stderr)

    def test_run_contract_rejects_grafana_before_v13(self) -> None:
        run = load_artifact(self.paths["run-contract"])
        run["schema"]["grafana_version"] = "12.4.0"
        self.write("grafana-v12-run", run)
        result = self.run_tool(VALIDATOR, self.paths["grafana-v12-run"], expected=1)
        self.assertIn("requires Grafana v13 or later", result.stderr)

    def test_coordinator_stage_preserves_namespace_scope_input_chain(self) -> None:
        command = (
            "import pathlib,sys; "
            f"sys.path.insert(0, {str(REPOSITORY / 'scripts')!r}); "
            "import coordinator_stage as stage; "
            "assert stage.direct_input_types('application-metrics') == {'run-contract'}; "
            "assert stage.direct_input_types('kubernetes-metrics') == "
            "{'run-contract', 'application-metrics'}; "
            "assert stage.direct_input_types('metrics-reviewer') == "
            "{'run-contract', 'application-metrics', 'kubernetes-metrics'}; "
            f"scope=stage.ticket_namespace_scope('kubernetes-metrics', "
            f"{{'application-metrics': pathlib.Path({str(self.paths['application-metrics'])!r})}}); "
            f"assert scope == {{'evidence_ref': {str(self.root / 'application-namespace-scope.yaml')!r}, "
            f"'sha256': {digest(self.root / 'application-namespace-scope.yaml')!r}}}"
        )
        self.run_tool("-c", command)

    def test_stage_check_validates_ticket_derived_metrics_draft(self) -> None:
        agent_root = self.root / "draft-agent"
        (agent_root / "tmp").mkdir(parents=True)
        (agent_root / "outbox").mkdir()
        (agent_root / "metrics.ndjson").write_bytes((self.root / "metrics.ndjson").read_bytes())
        draft = agent_root / "tmp" / "metrics-contract.yaml"
        draft.write_bytes(self.paths["metrics-contract"].read_bytes())
        ticket = {
            "agent": "metrics-reviewer",
            "outputs": {
                "artifact": "outbox/metrics-contract.yaml",
                "failure_report": "outbox/failure-report.yaml",
            },
        }
        command = (
            "import pathlib,sys; "
            f"sys.path.insert(0, {str(REPOSITORY / 'scripts')!r}); "
            "import stage_check; "
            f"ticket={ticket!r}; "
            f"agent_root=pathlib.Path({str(agent_root)!r}); "
            "inputs={"
            f"'run-contract': pathlib.Path({str(self.paths['run-contract'])!r}), "
            f"'application-metrics': pathlib.Path({str(self.paths['application-metrics'])!r}), "
            f"'kubernetes-metrics': pathlib.Path({str(self.paths['kubernetes-metrics'])!r})}}; "
            "assert stage_check.validate_draft(ticket, inputs, {}, agent_root) == "
            "agent_root / 'tmp' / 'metrics-contract.yaml'"
        )
        self.run_tool("-c", command)

    def test_kubernetes_presets_emit_documented_candidates_without_cross_profile_leakage(self) -> None:
        result = subprocess.run(
            [sys.executable, str(KUBERNETES_PRESETS), "--preset", "istio-workload"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        catalogue = json.loads(result.stdout)
        self.assertTrue(Path(catalogue["catalog_ref"]).is_file())
        self.assertEqual([f"I{index:03d}" for index in range(1, 11)],
                         [metric["id"] for metric in catalogue["metrics"]])
        for metric in catalogue["metrics"]:
            self.assertEqual("ISTIO", metric["source"])
            self.assertEqual("DOCUMENTED", metric["availability"])
            self.assertEqual([], metric["observed_labels"])
            self.assertTrue(metric["documented_labels"])

    def test_kubernetes_presets_checkpoint_the_complete_catalogue(self) -> None:
        initialized = subprocess.run(
            [str(INIT_WORKSPACE), str(self.root), "test-project", "test-run", "kubernetes-metrics"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, initialized.returncode, initialized.stdout + initialized.stderr)
        workspace = Path(initialized.stdout.strip())
        result = subprocess.run(
            [str(KUBERNETES_PRESETS), "--workspace", str(workspace)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual(23, json.loads(result.stdout.splitlines()[-1])["checkpoint_count"])
        self.assertEqual(23, len(list((workspace / "records" / "metrics").glob("*.yaml"))))
        self.assertEqual(23, len(list((workspace / "records" / "done").glob("*.yaml"))))
        self.assertEqual([], list((workspace / "records" / "pending").glob("*.yaml")))

    def test_coordinator_stage_requires_workspace_cwd(self) -> None:
        workspace = self.root / "dashboards" / "test-project" / "workspace"
        run_contract = workspace / "coordinator" / "test-run" / "outbox" / "run-contract.yaml"
        run_contract.parent.mkdir(parents=True)
        run_contract.write_bytes(self.paths["run-contract"].read_bytes())
        command = (
            "import pathlib,sys; "
            f"sys.path.insert(0, {str(REPOSITORY / 'scripts')!r}); "
            "import coordinator_stage as stage; "
            f"stage.load_run(pathlib.Path({str(run_contract)!r}))"
        )
        result = subprocess.run(
            [sys.executable, "-c", command],
            cwd=workspace,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        result = subprocess.run(
            [sys.executable, "-c", command],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("run coordinator commands from workspace", result.stderr)

    def test_specialist_ticket_tools_default_to_local_inbox(self) -> None:
        commands = (
            [COORDINATOR_STAGE, "validate-ticket", "--help"],
            [STAGE_CHECK, "--help"],
            [DASHBOARD_INTEGRITY, "--help"],
        )
        for command in commands:
            result = self.run_tool(*command)
            self.assertIn("[--ticket TICKET]", result.stdout)

    def test_reset_stage_reissues_ticket_without_changing_agent_workspace(self) -> None:
        workspace = self.root / "dashboards" / "test-project" / "workspace"
        initialized = subprocess.run(
            [str(INIT_WORKSPACE), str(self.root), "test-project", "test-run", "coordinator"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, initialized.returncode, initialized.stdout + initialized.stderr)
        run_contract = workspace / "coordinator" / "test-run" / "outbox" / "run-contract.yaml"
        run_contract.write_bytes(self.paths["run-contract"].read_bytes())
        coordinator_state = workspace / "coordinator" / "test-run" / "state.yaml"
        updated = subprocess.run(
            ["yq", "-i", '.status = "IN_PROGRESS" | .next_action = "dispatch-next-stage"', str(coordinator_state)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, updated.returncode, updated.stdout + updated.stderr)
        dispatched = subprocess.run(
            [
                str(COORDINATOR_STAGE), "dispatch", "--run-contract", str(run_contract),
                "--agent", "application-metrics",
            ],
            cwd=workspace,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, dispatched.returncode, dispatched.stdout + dispatched.stderr)
        agent_root = workspace / "application-metrics" / "test-run"
        ticket = agent_root / "inbox" / "job.yaml"
        state = agent_root / "state.yaml"
        before = {path: path.read_bytes() for path in (ticket, state)}
        reset = subprocess.run(
            [
                str(COORDINATOR_STAGE), "reset-stage", "--run-contract", str(run_contract),
                "--agent", "application-metrics",
            ],
            cwd=workspace,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, reset.returncode, reset.stdout + reset.stderr)
        self.assertTrue(reset.stdout.startswith("RESET application-metrics workspace="))
        self.assertIn(" agent_run=", reset.stdout)
        self.assertEqual(before, {path: path.read_bytes() for path in (ticket, state)})

    def test_run_contract_requires_project_workspace_layout(self) -> None:
        run = load_artifact(self.paths["run-contract"])
        run["workspace"] = str(self.root / "work")
        self.write("invalid-workspace-run", run)
        result = self.run_tool(
            VALIDATOR,
            self.paths["invalid-workspace-run"],
            expected=1,
        )
        self.assertIn("dashboards/<project-name>/workspace", result.stderr)

    def test_run_contract_requires_render_executable(self) -> None:
        run = load_artifact(self.paths["run-contract"])
        run["render"]["argv"][0] = "definitely-not-an-installed-render-tool"
        self.write("missing-render-tool-run", run)
        result = self.run_tool(VALIDATOR, self.paths["missing-render-tool-run"], expected=1)
        self.assertIn("render executable is unavailable", result.stderr)

    def test_run_contract_requires_locked_and_vendored_grafonnet_revision(self) -> None:
        lock = {
            "version": 1,
            "dependencies": [{
                "source": {"git": {
                    "remote": "https://github.com/grafana/grafonnet.git",
                    "subdir": "gen/grafonnet-v13.0.0",
                }},
                "version": "locked-revision",
                "sum": "unused",
            }],
            "legacyImports": False,
        }
        (self.root / "jsonnetfile.lock.json").write_text(json.dumps(lock), encoding="utf-8")
        vendor = self.root / "vendor/github.com/grafana/grafonnet/gen/grafonnet-v13.0.0"
        vendor.mkdir(parents=True)

        run = load_artifact(self.paths["run-contract"])
        run["schema"]["grafonnet_revision"] = "wrong-revision"
        self.write("wrong-pin-run", run)
        result = self.run_tool(VALIDATOR, self.paths["wrong-pin-run"], expected=1)
        self.assertIn("absent from jsonnetfile.lock.json", result.stderr)

        run["schema"]["grafonnet_revision"] = "locked-revision"
        self.write("locked-pin-run", run)
        self.run_tool(VALIDATOR, self.paths["locked-pin-run"])

        vendor.rmdir()
        result = self.run_tool(VALIDATOR, self.paths["locked-pin-run"], expected=1)
        self.assertIn("not vendored locally", result.stderr)

    def test_failure_report_requires_existing_evidence_file(self) -> None:
        report = self.envelope(
            "failure-report",
            "BLOCKED",
            {"run-contract": digest(self.paths["run-contract"])},
            failed_stage="application-metrics",
            owner="USER",
            code="MISSING_INPUT",
            summary="Required input is unavailable.",
            evidence_refs=["evidence/missing.yaml"],
        )
        self.write("missing-evidence-report", report)
        result = self.run_tool(
            VALIDATOR,
            self.paths["missing-evidence-report"],
            "--input",
            f"run-contract={self.paths['run-contract']}",
            expected=1,
        )
        self.assertIn("evidence reference does not identify a regular file", result.stderr)

    def test_parity_rejects_swapped_consumer_text(self) -> None:
        rendered = json.loads(self.rendered_path.read_text(encoding="utf-8"))
        panel_spec = rendered["spec"]["elements"]["P001"]["spec"]["data"]["spec"]["queries"][0]["spec"]["query"]["spec"]
        variable_spec = rendered["spec"]["variables"][1]["spec"]["query"]["spec"]
        panel_spec["expr"], variable_spec["query"] = variable_spec["query"], panel_spec["expr"]
        swapped = self.write("swapped-rendered", rendered)
        result = self.run_tool(
            PARITY,
            self.paths["query-pack"],
            self.paths["query-review"],
            swapped,
            expected=1,
        )
        self.assertIn("query consumer mismatch", result.stderr)

    def test_verifiers_reject_classic_dashboard_json(self) -> None:
        classic = {"panels": [], "templating": {"list": []}, "annotations": {"list": []}}
        classic_rendered = self.write("classic-rendered", classic)
        result = self.run_tool(
            PARITY,
            self.paths["query-pack"],
            self.paths["query-review"],
            classic_rendered,
            expected=1,
        )
        self.assertIn("Dashboard Schema V2 resources only", result.stderr)
        result = self.run_tool(NON_PROMETHEUS, classic_rendered, expected=1)
        self.assertIn("Dashboard Schema V2 resources only", result.stderr)

    def test_chain_rejects_destination_created_after_absent_baseline(self) -> None:
        (self.root / "dashboard.jsonnet").write_text("{ concurrent: true }\n", encoding="utf-8")
        result = self.run_tool(
            CHAIN,
            self.paths["run-contract"],
            self.paths["metrics-contract"],
            self.paths["dashboard-plan"],
            self.paths["query-pack"],
            self.paths["query-review"],
            self.paths["dashboard-build"],
            self.paths["dashboard-review"],
            "--application-metrics",
            self.paths["application-metrics"],
            "--promote",
            expected=1,
        )
        self.assertIn("appeared after absent baseline", result.stderr)
        self.assertIn("concurrent", (self.root / "dashboard.jsonnet").read_text(encoding="utf-8"))

    def test_chain_rejects_render_unrelated_to_candidate(self) -> None:
        candidate = self.root / "dashboard.candidate.jsonnet"
        candidate.write_text('{"unrelated": true}', encoding="utf-8")
        build = load_artifact(self.paths["dashboard-build"])
        build["candidate_sha256"] = digest(candidate)
        self.write("dashboard-build", build)
        review = load_artifact(self.paths["dashboard-review"])
        review["inputs"]["dashboard-build"] = digest(self.paths["dashboard-build"])
        review["build_manifest_sha256"] = digest(self.paths["dashboard-build"])
        review["candidate_sha256"] = digest(candidate)
        self.write("dashboard-review", review)
        result = self.run_tool(
            CHAIN,
            self.paths["run-contract"],
            self.paths["metrics-contract"],
            self.paths["dashboard-plan"],
            self.paths["query-pack"],
            self.paths["query-review"],
            self.paths["dashboard-build"],
            self.paths["dashboard-review"],
            "--application-metrics",
            self.paths["application-metrics"],
            "--promote",
            expected=1,
        )
        self.assertIn("recorded render is not the exact output", result.stderr)
        self.assertFalse((self.root / "dashboard.jsonnet").exists())

    def test_chain_rejects_unplanned_queryless_panel(self) -> None:
        rendered_path = self.rendered_path
        rendered = json.loads(rendered_path.read_text(encoding="utf-8"))
        rendered["spec"]["elements"]["P999"] = {"kind": "Panel", "spec": {"title": "Unplanned"}}
        rendered_json = json.dumps(rendered)
        rendered_path.write_text(rendered_json, encoding="utf-8")
        candidate = self.root / "dashboard.candidate.jsonnet"
        candidate.write_text(rendered_json, encoding="utf-8")
        build = load_artifact(self.paths["dashboard-build"])
        build["candidate_sha256"] = digest(candidate)
        build["rendered_sha256"] = digest(rendered_path)
        self.write("dashboard-build", build)
        review = load_artifact(self.paths["dashboard-review"])
        review["inputs"]["dashboard-build"] = digest(self.paths["dashboard-build"])
        review["build_manifest_sha256"] = digest(self.paths["dashboard-build"])
        review["candidate_sha256"] = digest(candidate)
        review["rendered_sha256"] = digest(rendered_path)
        self.write("dashboard-review", review)
        result = self.run_tool(
            CHAIN,
            self.paths["run-contract"],
            self.paths["metrics-contract"],
            self.paths["dashboard-plan"],
            self.paths["query-pack"],
            self.paths["query-review"],
            self.paths["dashboard-build"],
            self.paths["dashboard-review"],
            "--application-metrics",
            self.paths["application-metrics"],
            expected=1,
        )
        self.assertIn("panel IDs must exactly match", result.stderr)

    def test_final_render_verifier_rejects_arbitrary_source_path(self) -> None:
        unrelated = self.root / "unrelated.jsonnet"
        unrelated.write_bytes((self.root / "dashboard.candidate.jsonnet").read_bytes())
        result = self.run_tool(
            RENDER_VERIFIER,
            self.paths["run-contract"],
            self.paths["dashboard-build"],
            "--source",
            unrelated,
            expected=1,
        )
        self.assertIn("must be the promoted final source", result.stderr)

    def test_dashboard_contract_rejects_missing_variable_qry_type(self) -> None:
        rendered = json.loads(self.rendered_path.read_text(encoding="utf-8"))
        del rendered["spec"]["variables"][1]["spec"]["query"]["spec"]["qryType"]
        bad = self.write("missing-qry-type", rendered)
        result = self.run_tool(DASHBOARD_CONTRACT, bad, expected=1)
        self.assertIn("qryType is missing", result.stderr)

    def test_coordinator_stage_response_grammar_is_enforced(self) -> None:
        digest_value = "sha256:" + "a" * 64
        command = (
            "import sys; "
            f"sys.path.insert(0, {str(REPOSITORY / 'scripts')!r}); "
            "from coordinator_stage import RESPONSE_RE; "
            f"assert RESPONSE_RE.fullmatch('PASS promql-reviewer artifact=work/query-review.yaml sha256={digest_value}'); "
            "assert RESPONSE_RE.fullmatch('PASS promql-reviewer') is None"
        )
        self.run_tool("-c", command)

    def test_platform_atomic_exchange_swaps_without_deleting_either_file(self) -> None:
        first = self.root / "first.txt"
        second = self.root / "second.txt"
        first.write_text("first", encoding="utf-8")
        second.write_text("second", encoding="utf-8")
        code = (
            "import pathlib,sys;"
            "sys.path.insert(0,sys.argv[3]);"
            "from verify_workflow_chain import atomic_exchange;"
            "atomic_exchange(pathlib.Path(sys.argv[1]),pathlib.Path(sys.argv[2]))"
        )
        self.run_tool("-c", code, first, second, REPOSITORY / "scripts")
        self.assertEqual("second", first.read_text(encoding="utf-8"))
        self.assertEqual("first", second.read_text(encoding="utf-8"))

    def test_publish_report_requires_explicit_publish_intent(self) -> None:
        report = self.envelope(
            "publish-report",
            "PASS",
            {
                "run-contract": digest(self.paths["run-contract"]),
                "dashboard-build": digest(self.paths["dashboard-build"]),
                "dashboard-review": digest(self.paths["dashboard-review"]),
            },
            dashboard_review_sha256=digest(self.paths["dashboard-review"]),
            promoted_source_sha256=digest(self.root / "dashboard.candidate.jsonnet"),
            rendered_sha256=digest(self.rendered_path),
            operation="CREATE",
            write_status="PASS",
            readback_status="PASS",
            evidence_refs=["publish-evidence.json"],
        )
        self.write("publish-report", report)
        direct = {"run-contract", "dashboard-build", "dashboard-review"}
        result = self.run_tool(
            VALIDATOR,
            self.paths["publish-report"],
            "--input",
            f"run-contract={self.paths['run-contract']}",
            "--input",
            f"dashboard-build={self.paths['dashboard-build']}",
            "--input",
            f"dashboard-review={self.paths['dashboard-review']}",
            *self.support_arguments(direct),
            expected=1,
        )
        self.assertIn("publication was not requested", result.stderr)

    def test_agent_workspace_is_initialized_as_resumable_yaml(self) -> None:
        arguments = [
            str(INIT_WORKSPACE),
            str(self.root),
            "demo-project",
            "run-1",
            "application-metrics",
        ]
        first = subprocess.run(arguments, capture_output=True, text=True, check=False)
        self.assertEqual(0, first.returncode, first.stdout + first.stderr)
        agent_root = (
            self.root / "dashboards" / "demo-project" / "workspace"
            / "application-metrics" / "run-1"
        )
        for directory in {"inbox", "records", "records/done", "evidence", "outbox", "tmp"}:
            self.assertTrue((agent_root / directory).is_dir())
        state_path = agent_root / "state.yaml"
        state_raw = state_path.read_bytes()
        converted = subprocess.run(
            ["yq", "eval", "-o=json", ".", str(state_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, converted.returncode, converted.stdout + converted.stderr)
        state = json.loads(converted.stdout)
        self.assertEqual("application-metrics", state["agent"])
        self.assertEqual("run-1", state["run_id"])
        self.assertEqual("read-inbox", state["next_action"])

        second = subprocess.run(arguments, capture_output=True, text=True, check=False)
        self.assertEqual(0, second.returncode, second.stdout + second.stderr)
        self.assertEqual(state_raw, state_path.read_bytes())

        validation = subprocess.run(
            [str(VALIDATE_WORKSPACE), str(agent_root)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, validation.returncode, validation.stdout + validation.stderr)

    def test_agent_workspace_rejects_oversized_record(self) -> None:
        initialized = subprocess.run(
            [
                str(INIT_WORKSPACE),
                str(self.root),
                "demo-project",
                "run-2",
                "application-metrics",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, initialized.returncode, initialized.stdout + initialized.stderr)
        agent_root = Path(initialized.stdout.strip())
        record_dir = agent_root / "records" / "metrics"
        record_dir.mkdir()
        (record_dir / "0001-M001.yaml").write_text(
            "id: M001\nhelp: " + "x" * 8200 + "\n",
            encoding="utf-8",
        )
        result = subprocess.run(
            [str(VALIDATE_WORKSPACE), str(agent_root)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("exceeds 8192 bytes", result.stderr)

    def test_coordinator_helpers_create_valid_terminal_artifacts_and_state(self) -> None:
        helper_root = self.root / "helper-repository"
        helper_root.mkdir()
        workspace = helper_root / "dashboards/demo-project/workspace"
        workspace.mkdir(parents=True)
        jsonnet_dir = helper_root / "bin"
        jsonnet_dir.mkdir()
        jsonnet_tool = jsonnet_dir / "jsonnet"
        jsonnet_tool.write_text(
            "#!/bin/sh\ntest \"$1\" = -J && test \"$2\" = vendor || exit 1\ncat \"$3\"\n",
            encoding="utf-8",
        )
        jsonnet_tool.chmod(0o755)
        version_tool = helper_root / "grafana-version-tool"
        version_tool.write_text(
            "#!/bin/sh\n"
            "while [ \"$#\" -gt 0 ]; do\n"
            "  case \"$1\" in --output) output=$2; shift 2;; *) url=$1; shift;; esac\n"
            "done\n"
            "test \"$url\" = https://grafana.example.test/version || exit 1\n"
            "printf x >> \"$0.invocations\"\n"
            "printf '%s\\n' '{\"gitTreeState\":\"grafana v13.2.1\"}' > \"$output\"\n"
            "printf 200\n",
            encoding="utf-8",
        )
        version_tool.chmod(0o755)
        metrics_file = helper_root / "metrics.txt"
        metrics_file.write_text("metric 1\n", encoding="utf-8")
        environment_file = workspace / ".env"
        environment_file.write_text(
            "GRAFANA_TARGET=https://grafana.example.test\n"
            f"GRAFANA_HTTP_CLIENT={version_tool}\n"
            "GRAFANA_HTTP_CLIENT_ARGS_JSON=[\"--netrc\"]\n"
            f"METRICS_TARGET={metrics_file}\n"
            "METRICS_HTTP_CLIENT=\n"
            "METRICS_HTTP_CLIENT_ARGS_JSON=[]\n"
            "GRAFANA_PROMETHEUS_DATASOURCE_UID=prometheus-main\n"
            "WORKFLOW_RUN_ID=run-1\n"
            "WORKFLOW_DATASOURCE_ACCESS=true\n"
            "WORKFLOW_DASHBOARD_API_VALIDATION=true\n"
            "WORKFLOW_PUBLISH_REQUESTED=true\n",
            encoding="utf-8",
        )
        environment_file.chmod(0o600)
        lock = {
            "version": 1,
            "dependencies": [{
                "source": {"git": {
                    "remote": "https://github.com/grafana/grafonnet.git",
                    "subdir": "gen/grafonnet-v13.0.0",
                }},
                "version": "helper-revision",
                "sum": "unused",
            }],
            "legacyImports": False,
        }
        (helper_root / "jsonnetfile.lock.json").write_text(json.dumps(lock), encoding="utf-8")
        (helper_root / "vendor/github.com/grafana/grafonnet/gen/grafonnet-v13.0.0").mkdir(
            parents=True
        )

        environment = os.environ | {"PATH": f"{jsonnet_dir}:{os.environ['PATH']}"}
        create_run = subprocess.run(
            [
                sys.executable,
                str(CREATE_COORDINATOR_ARTIFACT),
                "run-contract",
            ],
            capture_output=True,
            text=True,
            check=False,
            cwd=workspace,
            env=environment,
        )
        self.assertEqual(0, create_run.returncode, create_run.stdout + create_run.stderr)
        repeated_run = subprocess.run(
            create_run.args, capture_output=True, text=True, check=False, cwd=workspace, env=environment,
        )
        self.assertEqual(1, repeated_run.returncode, repeated_run.stdout + repeated_run.stderr)
        self.assertIn("already invoked", repeated_run.stderr)
        conflicting_run = subprocess.run(
            [*create_run.args, "--datasource-access"],
            capture_output=True,
            text=True,
            check=False,
            cwd=workspace,
            env=environment,
        )
        self.assertEqual(2, conflicting_run.returncode, conflicting_run.stdout + conflicting_run.stderr)
        self.assertIn("unrecognized arguments", conflicting_run.stderr)
        self.assertEqual("x", Path(f"{version_tool}.invocations").read_text(encoding="utf-8"))
        coordinator = (
            helper_root / "dashboards/demo-project/workspace/coordinator/run-1"
        )
        run_contract = coordinator / "outbox/run-contract.yaml"
        run = load_artifact(run_contract)
        self.assertEqual("v13.2.1", run["schema"]["grafana_version"])
        self.assertEqual("helper-revision", run["schema"]["grafonnet_revision"])
        self.assertEqual(
            {
                "datasource_access": True,
                "dashboard_api_validation": True,
                "publish_requested": True,
            },
            run["capabilities"],
        )
        state = load_artifact(coordinator / "state.yaml")
        self.assertEqual("IN_PROGRESS", state["status"])

        evidence = coordinator / "evidence/runtime-capabilities.yaml"
        evidence.write_text("available: false\n", encoding="utf-8")
        create_failure = subprocess.run(
            [
                sys.executable,
                str(CREATE_COORDINATOR_ARTIFACT),
                "failure-report",
                "--run-contract",
                str(run_contract),
                "--status",
                "BLOCKED",
                "--failed-stage",
                "application-metrics",
                "--owner",
                "USER",
                "--code",
                "MISSING_SPECIALIST_RUNTIME",
                "--summary",
                "Required specialist runtime is unavailable.",
                "--evidence",
                "evidence/runtime-capabilities.yaml",
            ],
            capture_output=True,
            text=True,
            check=False,
            env=environment,
        )
        self.assertEqual(0, create_failure.returncode, create_failure.stdout + create_failure.stderr)
        repeated_failure = subprocess.run(
            create_failure.args,
            capture_output=True,
            text=True,
            check=False,
            env=environment,
        )
        self.assertEqual(
            0,
            repeated_failure.returncode,
            repeated_failure.stdout + repeated_failure.stderr,
        )
        validation = subprocess.run(
            [str(VALIDATE_WORKSPACE), str(coordinator)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, validation.returncode, validation.stdout + validation.stderr)
        state = load_artifact(coordinator / "state.yaml")
        self.assertEqual("BLOCKED", state["status"])
        self.assertEqual("complete", state["next_action"])

        subprocess.run(
            ["yq", "eval", "-i", '.status = "READY"', str(coordinator / "state.yaml")],
            check=True,
        )
        validation = subprocess.run(
            [str(VALIDATE_WORKSPACE), str(coordinator)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(1, validation.returncode, validation.stdout + validation.stderr)
        self.assertIn("does not match terminal", validation.stderr)

    def test_validator_rejects_json_stage_artifact(self) -> None:
        json_pack = self.root / "query-pack.json"
        json_pack.write_text(
            json.dumps(load_artifact(self.paths["query-pack"])),
            encoding="utf-8",
        )
        result = self.run_tool(
            VALIDATOR,
            json_pack,
            "--input",
            f"run-contract={self.paths['run-contract']}",
            "--input",
            f"metrics-contract={self.paths['metrics-contract']}",
            "--input",
            f"dashboard-plan={self.paths['dashboard-plan']}",
            *self.support_arguments({"run-contract", "metrics-contract", "dashboard-plan"}),
            expected=1,
        )
        self.assertIn("must use a .yaml filename", result.stderr)

    def test_validator_rejects_yml_stage_artifact(self) -> None:
        yml_pack = self.root / "query-pack.yml"
        yml_pack.write_bytes(self.paths["query-pack"].read_bytes())
        result = self.run_tool(
            VALIDATOR,
            yml_pack,
            "--input",
            f"run-contract={self.paths['run-contract']}",
            "--input",
            f"metrics-contract={self.paths['metrics-contract']}",
            "--input",
            f"dashboard-plan={self.paths['dashboard-plan']}",
            *self.support_arguments({"run-contract", "metrics-contract", "dashboard-plan"}),
            expected=1,
        )
        self.assertIn("must use a .yaml filename", result.stderr)

    def test_query_parity_rejects_json_pack_artifact(self) -> None:
        json_pack = self.root / "parity-query-pack.json"
        json_pack.write_text(
            json.dumps(load_artifact(self.paths["query-pack"])),
            encoding="utf-8",
        )
        result = self.run_tool(
            PARITY,
            json_pack,
            self.paths["query-review"],
            self.rendered_path,
            expected=1,
        )
        self.assertIn("must use a .yaml filename", result.stderr)


if __name__ == "__main__":
    unittest.main()
