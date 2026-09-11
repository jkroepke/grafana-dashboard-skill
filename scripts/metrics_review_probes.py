#!/usr/bin/env python3
"""Probe ticketed Kubernetes metric candidates within the application namespace scope."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import coordinator_stage as stage
from grafana_access import AccessError, grafana_access_from_environment, http_request, prometheus_request_url, write_response


class ProbeError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ProbeError(message)


def namespaces(application: dict[str, Any]) -> list[str]:
    scope = application.get("namespace_scope")
    require(isinstance(scope, dict) and isinstance(scope.get("evidence_ref"), str), "application namespace scope is unavailable")
    try:
        return stage.read_namespace_scope(Path(scope["evidence_ref"]))
    except stage.StageError as error:
        raise ProbeError("namespace scope evidence is invalid") from error


def namespace_matcher(values: list[str]) -> str:
    return "^(?:" + "|".join(re.escape(value) for value in values) + ")$"


def inspect(body: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return {"result": "INVALID_RESPONSE", "series_count": 0, "label_keys": []}
    if not isinstance(payload, dict) or payload.get("status") != "success" or not isinstance(payload.get("data"), list):
        return {"result": "API_ERROR", "series_count": 0, "label_keys": []}
    values = [item for item in payload["data"] if isinstance(item, dict)]
    return {
        "result": "SERIES" if values else "EMPTY",
        "series_count": len(values),
        "label_keys": sorted({key for item in values for key in item if isinstance(key, str)}),
    }


def completed_summary(output_dir: Path, candidates: list[dict[str, Any]], scope: list[str]) -> dict[str, Any]:
    require(output_dir.is_dir() and not output_dir.is_symlink(), "metrics-review probe output is not a directory")
    path = output_dir / "summary.json"
    require(path.is_file() and not path.is_symlink(), "metrics-review probe output is incomplete")
    try:
        summary = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProbeError("metrics-review probe summary is invalid") from error
    require(isinstance(summary, dict) and summary.get("schema_version") == 1 and summary.get("kind") == "metrics-review-probes", "metrics-review probe summary is invalid")
    entries = summary.get("probes")
    expected = [(item.get("id"), item.get("family")) for item in candidates]
    actual = [
        (item.get("id"), item.get("family")) if isinstance(item, dict) else (None, None)
        for item in entries
    ] if isinstance(entries, list) else []
    require(actual == expected and summary.get("namespace_scope") == scope, "metrics-review probe summary does not match current inputs")
    for identifier, _ in expected:
        require(isinstance(identifier, str), "Kubernetes candidate is incomplete")
        for directory in ("requests", "responses"):
            evidence = output_dir / directory / f"{identifier}.json"
            require(evidence.is_file() and not evidence.is_symlink(), "metrics-review probe evidence is incomplete")
    return summary


def probe(records: list[dict[str, Any]], scope: list[str], output_dir: Path, fetch: Callable[[dict[str, Any]], bytes]) -> dict[str, Any]:
    require(scope, "namespace scope is empty")
    output_dir = output_dir if output_dir.is_absolute() else Path.cwd() / output_dir
    candidates = [record for record in records if record.get("source") in {"KSM", "KUBELET", "SCRAPE", "SCHEDULER"}]
    require(candidates, "no Kubernetes metric candidates are available")
    if output_dir.exists():
        return completed_summary(output_dir, candidates, scope)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".metrics-review-probes.", dir=output_dir.parent) as temporary:
        draft = Path(temporary)
        requests, responses = draft / "requests", draft / "responses"
        requests.mkdir()
        responses.mkdir()
        entries: list[dict[str, Any]] = []
        matcher = namespace_matcher(scope)
        for record in candidates:
            identifier, family = record.get("id"), record.get("family")
            require(isinstance(identifier, str) and isinstance(family, str) and family, "Kubernetes candidate is incomplete")
            request = {"operation": "series", "params": {"match[]": f'{family}{{namespace=~"{matcher}"}}'}}
            request_path = requests / f"{identifier}.json"
            response_path = responses / f"{identifier}.json"
            request_path.write_text(json.dumps(request, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
            body = fetch(request)
            write_response(response_path, body)
            entries.append({
                "id": identifier,
                "family": family,
                "request_ref": f"requests/{request_path.name}",
                "response_ref": f"responses/{response_path.name}",
                **inspect(body),
            })
        summary = {"schema_version": 1, "kind": "metrics-review-probes", "namespace_scope": scope, "probes": entries}
        (draft / "summary.json").write_text(json.dumps(summary, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
        os.replace(draft, output_dir)
    return summary


def run(ticket_path: Path) -> dict[str, Any]:
    ticket, _, _, _, inputs, _ = stage.validate_ticket(ticket_path)
    require(ticket["agent"] == "metrics-reviewer", "ticket is not for metrics-reviewer")
    run_contract = stage.read_yaml(inputs["run-contract"])
    require(run_contract["capabilities"]["datasource_access"], "datasource access is not enabled")
    application = stage.read_yaml(inputs["application-metrics"])
    kubernetes = stage.read_yaml(inputs["kubernetes-metrics"])
    access = grafana_access_from_environment()
    return probe(
        kubernetes["metrics"], namespaces(application), ticket_path.parent.parent / "evidence" / "metrics-review-probes",
        lambda request: http_request(access, "GET", prometheus_request_url(access, request)),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticket", type=Path, default=Path("inbox/job.yaml"), help="ticket; defaults to inbox/job.yaml")
    args = parser.parse_args()
    try:
        summary = run(args.ticket)
    except (OSError, AccessError, ProbeError, stage.StageError, KeyError, TypeError) as error:
        print(f"FAIL metrics-review-probes: {error}", file=sys.stderr)
        return 1
    observed = sum(item["result"] == "SERIES" for item in summary["probes"])
    print(f"PASS metrics-review-probes candidates={len(summary['probes'])} observed={observed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
