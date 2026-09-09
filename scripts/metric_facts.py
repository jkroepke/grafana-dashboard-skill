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


def require(condition: bool, message: str) -> None:
    if not condition:
        raise FactsError(message)


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
    # Do not classify operational meaning from naming patterns.  The only result
    # here is observation copied from the parser, plus an explicit AI handoff.
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
        "classification": "NEEDS_AI",
    }


def emit(snapshot_dir: Path, output: Path) -> None:
    require(snapshot_dir.is_dir() and not snapshot_dir.is_symlink(), "snapshot directory is unavailable")
    manifest = yaml_object(snapshot_dir / "manifest.yaml")
    require(manifest.get("kind") == "metric-snapshot-manifest", "snapshot manifest is invalid")
    records = [fact(yaml_object(path)) for path in sorted(snapshot_dir.glob("*.yaml")) if path.name != "manifest.yaml"]
    require(records and len(records) == manifest.get("family_count"), "snapshot family count disagrees with manifest")
    require(not output.exists(), "output already exists")
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
