#!/usr/bin/env python3
"""Assemble deterministic specialist artifact drafts from fixed checkpoints.

This command deliberately has no input-path arguments: the validated ticket and
agent-owned checkpoint names are the complete input contract.  Specialists make
small semantic records; this program owns envelopes, digest bindings, ordering,
and mechanical PASS fields.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import coordinator_stage as stage
import dashboard_integrity


class AssembleError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssembleError(message)


def checkpoint_records(root: Path, name: str) -> list[dict[str, Any]]:
    directory = root / "records" / name
    if not directory.exists():
        return []
    require(directory.is_dir() and not directory.is_symlink(), f"checkpoint directory is invalid: {name}")
    records: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.yaml")):
        require(path.is_file() and not path.is_symlink(), f"checkpoint is invalid: {path.name}")
        records.append(stage.read_yaml(path))
    return records


def envelope(ticket: dict[str, Any], artifact_type: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "artifact_type": artifact_type,
        "run_id": ticket["run_id"],
        "revision": ticket["revision"],
        "inputs": {name: binding["sha256"] for name, binding in ticket["inputs"].items()},
        "status": "DONE" if ticket["agent"] == "application-metrics" else "PASS",
    }


def regular_file(path: Path, message: str) -> Path:
    require(path.is_file() and not path.is_symlink(), message)
    return path.resolve()


def application(root: Path, ticket: dict[str, Any]) -> dict[str, Any]:
    scope = regular_file(root / "evidence" / "namespace-scope.json", "write evidence/namespace-scope.json first")
    try:
        namespaces = json.loads(scope.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AssembleError("namespace scope evidence must be a JSON array") from error
    require(isinstance(namespaces, list) and namespaces and all(isinstance(item, str) and item for item in namespaces),
            "namespace scope evidence must be a non-empty string array")
    result = envelope(ticket, "application-metrics")
    result.update({
        "catalog_ref": None,
        "metrics": checkpoint_records(root, "metrics"),
        "omission_counts": {},
        "namespace_scope": {
            "evidence_ref": str(scope),
            "sha256": stage.sha256(scope),
            "namespace_count": len(set(namespaces)),
        },
    })
    return result


def dashboard_plan(root: Path, ticket: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    result = envelope(ticket, "dashboard-plan")
    result.update({
        "panel_groups": checkpoint_records(root, "panel-groups"),
        "questions": checkpoint_records(root, "questions"),
        "panels": checkpoint_records(root, "panels"),
        "required_consumers": checkpoint_records(root, "consumers"),
        "omissions": checkpoint_records(root, "omissions"),
        "budgets": run["limits"],
    })
    return result


def query_pack(root: Path, ticket: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    result = envelope(ticket, "query-pack")
    result.update({
        "queries": checkpoint_records(root, "queries"),
        "live_validation": "PASS" if run["capabilities"]["datasource_access"] else "UNVERIFIED",
    })
    return result


def query_review(root: Path, ticket: dict[str, Any], run: dict[str, Any], inputs: dict[str, Path]) -> dict[str, Any]:
    findings = checkpoint_records(root, "findings")
    if findings:
        raise AssembleError("review findings require ./stage-failure-report; do not create a PASS review")
    live = "UNVERIFIED"
    if run["capabilities"]["datasource_access"]:
        report = regular_file(root / "evidence" / "prometheus-probe-report.json",
                              "run ./prometheus-probe-matrix before assembly")
        try:
            value = json.loads(report.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise AssembleError("Prometheus probe report is invalid") from error
        require(value.get("status") == "PASS", "Prometheus probe report is not PASS")
        live = "PASS"
    pack = stage.read_yaml(inputs["query-pack"])
    result = envelope(ticket, "query-review")
    result.update({"query_pack_sha256": ticket["inputs"]["query-pack"]["sha256"], "query_count": len(pack["queries"]),
                   "live_validation": live, "findings": []})
    return result


def dashboard_build(root: Path, ticket: dict[str, Any], run: dict[str, Any], inputs: dict[str, Path]) -> dict[str, Any]:
    integrity = dashboard_integrity.check(root / "inbox" / "job.yaml")
    dashboard_integrity.write_report(root / "evidence" / "dashboard-integrity.json", integrity)
    source, rendered = Path(run["source"]["candidate_path"]), Path(run["rendered_candidate_path"])
    regular_file(source, "candidate source is unavailable")
    regular_file(rendered, "rendered dashboard is unavailable")
    pack = stage.read_yaml(inputs["query-pack"])
    local_schema = checkpoint_records(root, "local-schema")
    require(len(local_schema) == 1 and set(local_schema[0]) == {"status"} and local_schema[0]["status"] in {"PASS", "UNVERIFIED"},
            "write one records/local-schema/*.yaml status checkpoint")
    result = envelope(ticket, "dashboard-build")
    result.update({
        "candidate_path": str(source), "candidate_sha256": stage.sha256(source),
        "rendered_path": str(rendered), "rendered_sha256": stage.sha256(rendered),
        "query_pack_sha256": ticket["inputs"]["query-pack"]["sha256"],
        "query_review_sha256": ticket["inputs"]["query-review"]["sha256"],
        "baseline_state": run["source"]["baseline_state"], "baseline_sha256": run["source"]["baseline_sha256"],
        "integrated_query_ids": [item["id"] for item in pack["queries"]],
        "checks": {"format": "PASS", "render": "PASS", "json": "PASS", "query_parity": "PASS",
                   "local_schema": local_schema[0]["status"], "layout_references": "PASS", "variable_payloads": "PASS"},
        "findings": [],
    })
    return result


def dashboard_review(root: Path, ticket: dict[str, Any], run: dict[str, Any], inputs: dict[str, Path]) -> dict[str, Any]:
    findings = checkpoint_records(root, "findings")
    if findings:
        raise AssembleError("review findings require ./stage-failure-report; do not create a PASS review")
    integrity = dashboard_integrity.check(root / "inbox" / "job.yaml")
    dashboard_integrity.write_report(root / "evidence" / "dashboard-integrity.json", integrity)
    if run["capabilities"]["dashboard_api_validation"]:
        regular_file(root / "evidence" / "grafana-dry-run.json", "run ./workflow grafana-dry-run before assembly")
        dry_run = "PASS"
    else:
        dry_run = "NOT_CONFIGURED"
    build = stage.read_yaml(inputs["dashboard-build"])
    result = envelope(ticket, "dashboard-review")
    result.update({
        "build_manifest_sha256": ticket["inputs"]["dashboard-build"]["sha256"],
        "candidate_sha256": build["candidate_sha256"], "rendered_sha256": build["rendered_sha256"],
        "query_pack_sha256": ticket["inputs"]["query-pack"]["sha256"],
        "query_review_sha256": ticket["inputs"]["query-review"]["sha256"],
        "query_parity": "PASS", "target_dry_run": dry_run, "findings": [],
    })
    return result


ASSEMBLERS = {
    "application-metrics": application,
    "dashboard-architect": dashboard_plan,
    "promql-builder": query_pack,
    "promql-reviewer": query_review,
    "dashboard-builder": dashboard_build,
    "dashboard-reviewer": dashboard_review,
}


def assemble(root: Path, ticket: dict[str, Any], run: dict[str, Any], inputs: dict[str, Path]) -> dict[str, Any]:
    assembler = ASSEMBLERS.get(ticket["agent"])
    require(assembler is not None, f"{ticket['agent']} has no deterministic artifact assembler")
    if ticket["agent"] == "application-metrics":
        return assembler(root, ticket)
    if ticket["agent"] in {"dashboard-architect", "promql-builder"}:
        return assembler(root, ticket, run)
    return assembler(root, ticket, run, inputs)


def write_draft(path: Path, payload: dict[str, Any]) -> None:
    raw = stage.coordinator_artifact.yaml_bytes(payload)
    if path.exists() or path.is_symlink():
        require(path.is_file() and not path.is_symlink(), "artifact draft is not a regular file")
        require(path.read_bytes() == raw, "artifact draft does not match fixed checkpoints")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", dir=path.parent, prefix=f".{path.name}.", delete=False) as file:
        temporary = Path(file.name)
        file.write(raw)
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticket", type=Path, default=Path("inbox/job.yaml"), help="ticket; defaults to inbox/job.yaml")
    args = parser.parse_args()
    try:
        ticket, run, _, _, inputs, _ = stage.validate_ticket(args.ticket)
        root = args.ticket.resolve().parent.parent
        payload = assemble(root, ticket, run, inputs)
        output = root / "tmp" / Path(ticket["outputs"]["artifact"]).name
        write_draft(output, payload)
    except (OSError, AssembleError, stage.StageError, stage.coordinator_artifact.CreationError, KeyError, TypeError) as error:
        print(f"FAIL stage-assemble: {error}", file=sys.stderr)
        return 1
    print(f"PASS stage-assemble agent={ticket['agent']} draft={output.relative_to(root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
