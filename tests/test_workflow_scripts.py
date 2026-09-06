from __future__ import annotations

import copy
import hashlib
import json
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
RESPONSE_VALIDATOR = REPOSITORY / "scripts" / "validate_stage_response.py"
NON_PROMETHEUS = REPOSITORY / "scripts" / "verify_non_prometheus_preservation.py"
RENDER_VERIFIER = REPOSITORY / "scripts" / "verify_candidate_render.py"


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


class WorkflowScriptsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.paths: dict[str, Path] = {}
        self._write_valid_pipeline()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write(self, name: str, value: object) -> Path:
        path = self.root / f"{name}.json"
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
            artifact_value = json.loads(self.paths[name].read_text(encoding="utf-8"))
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
        final_source = self.root / "dashboard.jsonnet"
        candidate_source = self.root / "dashboard.candidate.jsonnet"
        rendered = self.root / "rendered.json"
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
            workspace=str(self.root / "work"),
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
        )
        self.write("application-metrics", app)

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
        self.run_tool(PARITY, self.paths["query-pack"], self.paths["query-review"], self.root / "rendered.json")
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
        plan = json.loads(self.paths["dashboard-plan"].read_text(encoding="utf-8"))
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
        review = json.loads(self.paths["query-review"].read_text(encoding="utf-8"))
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
        plan = json.loads(self.paths["dashboard-plan"].read_text(encoding="utf-8"))
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

    def test_query_pack_rejects_literal_datasource(self) -> None:
        pack = json.loads(self.paths["query-pack"].read_text(encoding="utf-8"))
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
        app = json.loads(self.paths["application-metrics"].read_text(encoding="utf-8"))
        source_metric = app["metrics"][0]
        source_metric["family"] = "http_requests_total"
        source_metric["members"] = ["http_requests_total"]
        source_metric["type"] = "gauge"
        gauge_app = self.write("gauge-application-metrics", app)

        metrics = json.loads(self.paths["metrics-contract"].read_text(encoding="utf-8"))
        metrics["inputs"]["application-metrics"] = digest(gauge_app)
        approved = metrics["approved"][0]
        approved["family"] = "http_requests_total"
        approved["type"] = "gauge"
        gauge_metrics = self.write("gauge-metrics-contract", metrics)

        plan = json.loads(self.paths["dashboard-plan"].read_text(encoding="utf-8"))
        plan["inputs"]["metrics-contract"] = digest(gauge_metrics)
        gauge_plan = self.write("gauge-dashboard-plan", plan)

        pack = json.loads(self.paths["query-pack"].read_text(encoding="utf-8"))
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
        plan = json.loads(self.paths["dashboard-plan"].read_text(encoding="utf-8"))
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
        plan = json.loads(self.paths["dashboard-plan"].read_text(encoding="utf-8"))
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
        metrics = json.loads(self.paths["metrics-contract"].read_text(encoding="utf-8"))
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
        plan = json.loads(self.paths["dashboard-plan"].read_text(encoding="utf-8"))
        plan["hidden"] = "invalid"
        invalid_plan = self.write("invalid-upstream-plan", plan)
        pack = json.loads(self.paths["query-pack"].read_text(encoding="utf-8"))
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
        run = json.loads(self.paths["run-contract"].read_text(encoding="utf-8"))
        outside = self.root.parent / "outside-dashboard.jsonnet"
        run["source"]["final_path"] = str(outside)
        run["source"]["candidate_path"] = str(self.root.parent / "outside-dashboard.candidate.jsonnet")
        self.write("outside-run", run)
        result = self.run_tool(VALIDATOR, self.paths["outside-run"], expected=1)
        self.assertIn("inside repository_root", result.stderr)

    def test_parity_rejects_swapped_consumer_text(self) -> None:
        rendered = json.loads((self.root / "rendered.json").read_text(encoding="utf-8"))
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

    def test_classic_parity_ignores_explicit_loki_consumer(self) -> None:
        pack = json.loads(self.paths["query-pack"].read_text(encoding="utf-8"))
        pack["queries"][0]["consumer_locator"]["name"] = "panel-1"
        classic_pack = self.write("classic-pack", pack)
        review = json.loads(self.paths["query-review"].read_text(encoding="utf-8"))
        review["query_pack_sha256"] = digest(classic_pack)
        review["inputs"]["query-pack"] = digest(classic_pack)
        classic_review = self.write("classic-review", review)
        expressions = [record["expression"] for record in pack["queries"]]
        editor_ref = "PrometheusVariableQueryEditor-VariableQuery"
        classic = {
            "panels": [
                {
                    "id": 1,
                    "datasource": {"type": "prometheus", "uid": "${datasource}"},
                    "targets": [{"refId": "A", "expr": expressions[0]}],
                },
                {
                    "id": 2,
                    "datasource": {"type": "loki", "uid": "logs"},
                    "targets": [{"refId": "A", "expr": "{service=\"example\"}"}],
                },
            ],
            "templating": {
                "list": [
                    {"name": "datasource", "type": "datasource", "query": "prometheus"},
                    {
                        "name": "namespace",
                        "type": "query",
                        "datasource": {"type": "prometheus", "uid": "${datasource}"},
                        "query": {"query": expressions[1], "refId": editor_ref, "qryType": 1},
                    },
                    {
                        "name": "pod",
                        "type": "query",
                        "datasource": {"type": "prometheus", "uid": "${datasource}"},
                        "query": {"query": expressions[2], "refId": editor_ref, "qryType": 1},
                    },
                ]
            },
            "annotations": {"list": []},
        }
        classic_rendered = self.write("classic-rendered", classic)
        self.run_tool(PARITY, classic_pack, classic_review, classic_rendered)
        changed = copy.deepcopy(classic)
        changed["panels"][1]["targets"][0]["expr"] = "{service=\"changed\"}"
        changed_rendered = self.write("changed-classic-rendered", changed)
        result = self.run_tool(
            NON_PROMETHEUS,
            changed_rendered,
            "--baseline",
            classic_rendered,
            expected=1,
        )
        self.assertIn("non-Prometheus consumers changed", result.stderr)

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
        build = json.loads(self.paths["dashboard-build"].read_text(encoding="utf-8"))
        build["candidate_sha256"] = digest(candidate)
        self.write("dashboard-build", build)
        review = json.loads(self.paths["dashboard-review"].read_text(encoding="utf-8"))
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
        rendered_path = self.root / "rendered.json"
        rendered = json.loads(rendered_path.read_text(encoding="utf-8"))
        rendered["spec"]["elements"]["P999"] = {"kind": "Panel", "spec": {"title": "Unplanned"}}
        rendered_json = json.dumps(rendered)
        rendered_path.write_text(rendered_json, encoding="utf-8")
        candidate = self.root / "dashboard.candidate.jsonnet"
        candidate.write_text(rendered_json, encoding="utf-8")
        build = json.loads(self.paths["dashboard-build"].read_text(encoding="utf-8"))
        build["candidate_sha256"] = digest(candidate)
        build["rendered_sha256"] = digest(rendered_path)
        self.write("dashboard-build", build)
        review = json.loads(self.paths["dashboard-review"].read_text(encoding="utf-8"))
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
        rendered = json.loads((self.root / "rendered.json").read_text(encoding="utf-8"))
        del rendered["spec"]["variables"][1]["spec"]["query"]["spec"]["qryType"]
        bad = self.write("missing-qry-type", rendered)
        result = self.run_tool(DASHBOARD_CONTRACT, bad, expected=1)
        self.assertIn("qryType is missing", result.stderr)

    def test_stage_response_grammar_is_enforced(self) -> None:
        digest_value = "sha256:" + "a" * 64
        valid = self.root / "response.txt"
        valid.write_text(
            f"PASS promql-reviewer artifact=work/query-review.json sha256={digest_value}\n",
            encoding="utf-8",
        )
        self.run_tool(RESPONSE_VALIDATOR, valid)
        valid.write_text("PASS promql-reviewer\nextra context\n", encoding="utf-8")
        result = self.run_tool(RESPONSE_VALIDATOR, valid, expected=1)
        self.assertIn("one line", result.stderr)

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
            rendered_sha256=digest(self.root / "rendered.json"),
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


if __name__ == "__main__":
    unittest.main()
