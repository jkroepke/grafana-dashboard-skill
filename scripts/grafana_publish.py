#!/usr/bin/env python3
"""Deterministically publish an approved Dashboard Schema V2 resource.

The script owns the only mutable API transaction: preflight, existing-resource
GET, create-or-replace, readback, mechanical integrity checks, and report.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import quote

import coordinator_stage as stage
import dashboard_integrity
import verify_dashboard_contract as dashboard_contract
import verify_query_parity as query_parity
from grafana_access import AccessError, grafana_access_from_environment, grafana_url, http_response, write_response
from grafana_dry_run import replacement


COLLECTION = "/apis/dashboard.grafana.app/v2/namespaces/default/dashboards"
ITEM = COLLECTION + "/{}"


class PublishError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise PublishError(message)


def read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as error:
        raise PublishError(f"cannot read {label}") from error
    require(isinstance(value, dict), f"{label} is not an object")
    return value


def write_json_new(path: Path, value: dict[str, Any]) -> None:
    require(not path.exists(), f"{path.name} already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")


def verify_readback(resource: dict[str, Any], pack: dict[str, Any], expected_name: str) -> None:
    metadata = resource.get("metadata")
    require(isinstance(metadata, dict) and metadata.get("name") == expected_name, "readback resource identity changed")
    namespace = metadata.get("namespace")
    require(namespace in {None, "default"}, "readback resource namespace is not default")
    dashboard_contract.verify(resource)
    expected, _ = query_parity.approved_consumers(pack)
    require(expected == query_parity.v2_consumers(resource), "readback query parity failed")


def write_artifact(
    agent_root: Path, ticket: dict[str, Any], review: dict[str, Any], operation: str, write: Path, readback: Path,
) -> str:
    artifact = {
        "schema_version": 1,
        "artifact_type": "publish-report",
        "run_id": ticket["run_id"],
        "revision": ticket["revision"],
        "inputs": {name: binding["sha256"] for name, binding in ticket["inputs"].items()},
        "status": "PASS",
        "dashboard_review_sha256": ticket["inputs"]["dashboard-review"]["sha256"],
        "promoted_source_sha256": ticket["inputs"]["dashboard-review"]["sha256"],  # replaced below from review
        "rendered_sha256": ticket["inputs"]["dashboard-review"]["sha256"],  # replaced below from review
        "operation": operation,
        "write_status": "PASS",
        "readback_status": "PASS",
        "evidence_refs": [str(write.relative_to(agent_root)), str(readback.relative_to(agent_root))],
    }
    artifact["promoted_source_sha256"] = review["candidate_sha256"]
    artifact["rendered_sha256"] = review["rendered_sha256"]
    draft = agent_root / "tmp" / "publish-report.yaml"
    stage.atomic_yaml(draft, artifact)
    check = subprocess.run([sys.executable, str(Path(__file__).with_name("stage_check.py")), "--draft"], cwd=agent_root, capture_output=True, text=True, check=False)
    require(check.returncode == 0, check.stderr.strip() or "publish report draft validation failed")
    final = agent_root / ticket["outputs"]["artifact"]
    os.replace(draft, final)
    terminal = subprocess.run([sys.executable, str(Path(__file__).with_name("stage_check.py"))], cwd=agent_root, capture_output=True, text=True, check=False)
    require(terminal.returncode == 0, terminal.stderr.strip() or "publish report validation failed")
    return terminal.stdout.strip()


def write_failure(ticket_path: Path) -> str:
    """Terminally record an opaque deterministic failure when the ticket is valid."""
    ticket, _, _, _, _, _ = stage.validate_ticket(ticket_path)
    require(ticket["agent"] == "dashboard-publisher", "ticket is not for dashboard-publisher")
    agent_root = ticket_path.resolve().parent.parent
    evidence = agent_root / "evidence" / "publish-error.yaml"
    if not evidence.exists():
        stage.atomic_yaml(evidence, {"schema_version": 1, "kind": "publish-error", "code": "PUBLISH_FAILED"})
    report = {
        "schema_version": 1,
        "artifact_type": "failure-report",
        "run_id": ticket["run_id"],
        "revision": ticket["revision"],
        "inputs": {"run-contract": ticket["inputs"]["run-contract"]["sha256"]},
        "status": "FAIL",
        "failed_stage": "dashboard-publisher",
        "owner": "dashboard-publisher",
        "code": "PUBLISH_FAILED",
        "summary": "Deterministic Grafana publication did not complete.",
        "evidence_refs": [str(evidence.relative_to(agent_root))],
    }
    draft = agent_root / "tmp" / "failure-report.yaml"
    stage.atomic_yaml(draft, report)
    check = subprocess.run([sys.executable, str(Path(__file__).with_name("stage_check.py")), "--draft"], cwd=agent_root, capture_output=True, text=True, check=False)
    require(check.returncode == 0, check.stderr.strip() or "publish failure report draft validation failed")
    final = agent_root / ticket["outputs"]["failure_report"]
    os.replace(draft, final)
    terminal = subprocess.run([sys.executable, str(Path(__file__).with_name("stage_check.py"))], cwd=agent_root, capture_output=True, text=True, check=False)
    require(terminal.returncode == 0, terminal.stderr.strip() or "publish failure report validation failed")
    return terminal.stdout.strip()


def publish(ticket_path: Path) -> str:
    ticket, run, _, workspace, inputs, supports = stage.validate_ticket(ticket_path)
    require(ticket["agent"] == "dashboard-publisher", "ticket is not for dashboard-publisher")
    require(run["capabilities"]["publish_requested"], "publication was not requested")
    review = stage.read_yaml(inputs["dashboard-review"])
    require(review["status"] == "PASS", "dashboard review is not PASS")
    dashboard_integrity.check(ticket_path)
    build = stage.read_yaml(inputs["dashboard-build"])
    candidate = read_json(Path(build["rendered_path"]), "reviewed rendered dashboard")
    metadata = candidate.get("metadata")
    require(isinstance(metadata, dict) and isinstance(metadata.get("name"), str) and metadata["name"],
            "rendered dashboard has no metadata.name")
    name = metadata["name"]
    access = grafana_access_from_environment()
    item_url = grafana_url(access, ITEM.format(quote(name, safe="")))
    status, current = http_response(access, "GET", item_url, expected_status=(200, 404))
    agent_root = ticket_path.resolve().parent.parent
    write_path, readback_path = agent_root / "evidence" / "publish-write.json", agent_root / "evidence" / "publish-readback.json"
    require(not write_path.exists() and not readback_path.exists(), "publish evidence already exists")
    if status == 404:
        operation, method, url, request = "CREATE", "POST", grafana_url(access, COLLECTION), Path(build["rendered_path"])
        response_statuses = (200, 201)
        temporary = None
    else:
        operation, method, url = "UPDATE", "PUT", item_url
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=agent_root / "tmp", prefix=".publish-update.", suffix=".json", delete=False) as file:
            temporary = Path(file.name)
        replacement(candidate, current, temporary)
        request, response_statuses = temporary, (200, 201)
    try:
        _, written = http_response(access, method, url, request_file=request, headers=("Content-Type: application/json",), expected_status=response_statuses)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    write_response(write_path, written)
    _, readback = http_response(access, "GET", item_url, expected_status=200)
    write_response(readback_path, readback)
    verify_readback(read_json(readback_path, "publish readback"), stage.read_yaml({**inputs, **supports}["query-pack"]), name)
    return write_artifact(agent_root, ticket, review, operation, write_path, readback_path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticket", type=Path, default=Path("inbox/job.yaml"), help="ticket; defaults to inbox/job.yaml")
    args = parser.parse_args()
    try:
        print(publish(args.ticket))
    except (OSError, PublishError, AccessError, stage.StageError, dashboard_integrity.IntegrityError,
            dashboard_contract.ContractError, query_parity.ParityError, KeyError, TypeError) as error:
        try:
            print(write_failure(args.ticket))
        except (OSError, PublishError, AccessError, stage.StageError, KeyError, TypeError):
            pass
        print(f"FAIL grafana-publish: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
