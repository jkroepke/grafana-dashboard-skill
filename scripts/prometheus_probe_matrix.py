#!/usr/bin/env python3
"""Run declared Prometheus probes and record mechanical response evidence.

The matrix supplies concrete variable substitutions and cardinality bounds.
This program does not choose values or decide metric meaning; it only proves
whether the declared probe contract was observed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import coordinator_stage as stage
from grafana_access import AccessError, grafana_access_from_environment, http_request, prometheus_request_url


class ProbeError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ProbeError(message)


def read_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as error:
        raise ProbeError(f"{label} must be valid JSON") from error


def series(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        if data and not isinstance(data[0], dict):
            return []
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict) and isinstance(data.get("result"), list):
        return [item for item in data["result"] if isinstance(item, dict)]
    return []


def inspect(probe: dict[str, Any], body: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as error:
        raise ProbeError("Prometheus response is not JSON") from error
    require(isinstance(payload, dict) and payload.get("status") == "success", "Prometheus response status is not success")
    warnings = payload.get("warnings", [])
    require(isinstance(warnings, list) and not warnings, "Prometheus response contains warnings")
    values = series(payload.get("data"))
    count = len(values)
    minimum = probe.get("min_series", 0)
    maximum = probe.get("max_series", 10000)
    require(isinstance(minimum, int) and isinstance(maximum, int) and 0 <= minimum <= maximum <= 10000,
            "probe series bounds are invalid")
    require(minimum <= count <= maximum,
            f"probe {probe['id']}: observed series count {count} is outside declared bounds [{minimum}, {maximum}]")
    labels = probe.get("identity_labels", [])
    require(isinstance(labels, list) and len(labels) <= 8 and all(isinstance(item, str) and item for item in labels),
            "identity_labels is invalid")
    identities: set[tuple[str | None, ...]] = set()
    keys: set[str] = set()
    for value in values:
        metric = value.get("metric", {})
        if not isinstance(metric, dict):
            continue
        keys.update(key for key in metric if isinstance(key, str))
        identity = tuple(metric.get(label) if isinstance(metric.get(label), str) else None for label in labels)
        require(identity not in identities, "duplicate declared label identity")
        identities.add(identity)
    return {"id": probe["id"], "series_count": count, "label_keys": sorted(keys), "identity_labels": labels,
            "status": "PASS"}


def run(matrix_path: Path, output: Path, response_dir: Path) -> None:
    matrix = read_json(matrix_path, "probe matrix")
    require(isinstance(matrix, dict) and set(matrix) == {"probes"}, "probe matrix must contain only probes")
    probes = matrix["probes"]
    require(isinstance(probes, list) and 1 <= len(probes) <= 64, "probe matrix probes is invalid")
    require(not output.exists() and not response_dir.exists(), "probe output already exists")
    access = grafana_access_from_environment()
    response_dir.mkdir(parents=True)
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for probe in probes:
        require(isinstance(probe, dict) and set(probe) <= {"id", "operation", "params", "identity_labels", "min_series", "max_series"},
                "probe has unknown fields")
        identifier = probe.get("id")
        require(isinstance(identifier, str) and identifier and identifier.replace("-", "").replace("_", "").isalnum(), "probe id is invalid")
        require(identifier not in seen, "duplicate probe id")
        seen.add(identifier)
        request = {"operation": probe.get("operation"), "params": probe.get("params")}
        body = http_request(access, "GET", prometheus_request_url(access, request))
        response = response_dir / f"{identifier}.json"
        response.write_bytes(body)
        try:
            results.append(inspect(probe, body))
        except ProbeError as error:
            raise ProbeError(f"response={response}: {error}") from error
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"schema_version": 1, "kind": "prometheus-probe-report", "status": "PASS", "probes": results}, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticket", type=Path, default=Path("inbox/job.yaml"), help="ticket; defaults to inbox/job.yaml")
    parser.add_argument("--matrix", type=Path, default=Path("evidence/probe-matrix.json"))
    parser.add_argument("--output", type=Path, default=Path("evidence/prometheus-probe-report.json"))
    parser.add_argument("--responses", type=Path, default=Path("evidence/prometheus-probes"))
    args = parser.parse_args()
    try:
        ticket, _, _, _, _, _ = stage.validate_ticket(args.ticket)
        require(ticket["agent"] == "promql-reviewer", "ticket is not for promql-reviewer")
        run(args.matrix, args.output, args.responses)
    except (OSError, ProbeError, AccessError, stage.StageError, KeyError, TypeError) as error:
        print(f"FAIL prometheus-probe-matrix: {error}", file=sys.stderr)
        return 1
    print("PASS prometheus-probe-matrix")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
