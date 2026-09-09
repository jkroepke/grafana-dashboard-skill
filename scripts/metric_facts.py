#!/usr/bin/env python3
"""Emit a bounded, fact-only metric inventory from metric snapshot records."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


class FactsError(ValueError):
    pass


KNOWN_PROCESS_FAMILIES = {
    "fastapi_app_info": "FastAPI application identity metadata",
}
HTTP_SERVER_FAMILIES = {
    "http_requests_total": ("counter", {"handler", "method", "status"}, "total number of requests"),
    "http_request_size_bytes": ("summary", {"handler"}, "content length of incoming requests"),
    "http_response_size_bytes": ("summary", {"handler"}, "content length of outgoing responses"),
    "http_request_duration_seconds": ("histogram", {"handler", "method"}, "latency with"),
    "http_request_duration_highr_seconds": ("histogram", set(), "latency with"),
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise FactsError(message)


def process_classification(family: str) -> str | None:
    """Return only pinned framework/build metadata classifications."""
    if family in KNOWN_PROCESS_FAMILIES:
        return KNOWN_PROCESS_FAMILIES[family]
    if family.endswith("_build_info") and len(family) > len("_build_info"):
        return "build identity metadata"
    return None


def pinned_classification(record: dict[str, Any]) -> tuple[str, str] | None:
    """Classify only exact, evidence-checked framework families."""
    family = record.get("family")
    if not isinstance(family, str):
        return None
    process = process_classification(family)
    if process:
        return "PROCESS", process
    expected = HTTP_SERVER_FAMILIES.get(family)
    if expected is None:
        return None
    metric_type, required_labels, help_fragment = expected
    labels = record.get("observed_labels")
    help_text = record.get("help")
    if (
        record.get("declared_type") == metric_type
        and isinstance(labels, list)
        and all(isinstance(label, str) for label in labels)
        and required_labels <= set(labels)
        and isinstance(help_text, str)
        and help_fragment in help_text.lower()
    ):
        return "BUSINESS", "FastAPI server workload instrumentation"
    return None


def yaml_object(path: Path) -> dict[str, Any]:
    result = subprocess.run(["yq", "eval", "-o=json", ".", str(path)], capture_output=True, text=True, check=False)
    require(result.returncode == 0, f"cannot read snapshot {path.name}")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise FactsError(f"cannot decode snapshot {path.name}") from error
    require(isinstance(value, dict), f"snapshot {path.name} is not an object")
    return value


def fact(record: dict[str, Any]) -> dict[str, Any]:
    required = {
        "id", "family", "declared_type", "unit", "help", "members", "observed_labels",
        "sample_count", "has_timestamps", "has_exemplars", "source_ref", "warnings",
    }
    require(required <= set(record), "snapshot record is incomplete")
    require(record.get("kind") == "metric-family-snapshot", "record is not a metric snapshot")
    # Exact, pinned framework families are safe to classify. Everything else is
    # deliberately left to evidence-backed judgment rather than name heuristics.
    known = pinned_classification(record)
    return {
        "id": record["id"],
        "family": record["family"],
        "declared_type": record["declared_type"],
        "unit": record["unit"],
        "help": record["help"],
        "members": record["members"],
        "observed_labels": record["observed_labels"],
        "sample_count": record["sample_count"],
        "has_timestamps": record["has_timestamps"],
        "has_exemplars": record["has_exemplars"],
        "source_ref": record["source_ref"],
        "warnings": record["warnings"],
        "classification": known[0] if known else "NEEDS_AI",
        "classification_reason": known[1] if known else None,
    }


def completed_facts(output: Path, manifest: dict[str, Any], records: list[dict[str, Any]]) -> None:
    require(output.is_file() and not output.is_symlink(), "fact inventory is not a regular file")
    try:
        payload = json.loads(output.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise FactsError("fact inventory is invalid") from error
    require(isinstance(payload, dict) and payload.get("schema_version") == 1 and payload.get("kind") == "metric-facts", "fact inventory is invalid")
    require(payload.get("source") == manifest, "fact inventory does not match current snapshots")
    observed = payload.get("families")
    require(isinstance(observed, list), "fact inventory is invalid")
    expected_ids = [(record["id"], record["family"]) for record in records]
    actual_ids = [
        (record.get("id"), record.get("family")) if isinstance(record, dict) else (None, None)
        for record in observed
    ]
    require(actual_ids == expected_ids, "fact inventory does not match current snapshots")


def emit(snapshot_dir: Path, output: Path) -> None:
    require(snapshot_dir.is_dir() and not snapshot_dir.is_symlink(), "snapshot directory is unavailable")
    manifest = yaml_object(snapshot_dir / "manifest.yaml")
    require(manifest.get("kind") == "metric-snapshot-manifest", "snapshot manifest is invalid")
    records = [fact(yaml_object(path)) for path in sorted(snapshot_dir.glob("*.yaml")) if path.name != "manifest.yaml"]
    require(records and len(records) == manifest.get("family_count"), "snapshot family count disagrees with manifest")
    if output.exists() or output.is_symlink():
        completed_facts(output, manifest, records)
        return
    payload = {"schema_version": 1, "kind": "metric-facts", "source": manifest, "families": records}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    require(len(encoded.encode()) <= 256 * 1024, "fact inventory exceeds 256 KiB")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(encoded, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-dir", type=Path, default=Path("records/pending"))
    parser.add_argument("--output", type=Path, default=Path("evidence/metric-facts.json"))
    args = parser.parse_args()
    try:
        emit(args.snapshot_dir, args.output)
    except (OSError, FactsError) as error:
        print(f"FAIL metric-facts: {error}", file=sys.stderr)
        return 1
    print("PASS metric-facts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
