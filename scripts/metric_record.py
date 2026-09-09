#!/usr/bin/env python3
"""Create one application-metric checkpoint from an observed snapshot."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from metric_facts import process_classification


class RecordError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RecordError(message)


def yaml_object(path: Path) -> dict[str, Any]:
    result = subprocess.run(["yq", "eval", "-o=json", ".", str(path)], capture_output=True, text=True, check=False)
    require(result.returncode == 0, f"cannot read snapshot {path.name}")
    value = json.loads(result.stdout)
    require(isinstance(value, dict) and value.get("kind") == "metric-family-snapshot", "input is not a metric snapshot")
    return value


def create(item: str, record_id: str, category: str | None) -> Path:
    root = Path.cwd().resolve()
    pending = root / "records" / "pending"
    require((root / "records" / "done").is_dir() and (root / "state.yaml").is_file(), "run from an initialized metric-agent workspace")
    require(Path(item).name == item and item.endswith(".yaml") and item != "manifest.yaml", "item must be one pending YAML filename")
    snapshot = pending / item
    require(snapshot.is_file() and not snapshot.is_symlink(), "pending snapshot is unavailable")
    require(record_id.startswith("M") and record_id[1:].isdigit(), "record ID must look like M001")
    observed = yaml_object(snapshot)
    known = process_classification(str(observed.get("family", "")))
    category = category or ("PROCESS" if known else None)
    require(category in {"BUSINESS", "PROCESS"}, "category BUSINESS or PROCESS is required for an unclassified family")
    output = root / "records" / "metrics" / f"{record_id}.yaml"
    require(not output.exists(), f"checkpoint already exists: {output.relative_to(root)}")
    record = {
        "id": record_id,
        "source": "PROCESS" if category == "PROCESS" else "APPLICATION",
        "category": category,
        "family": observed["family"],
        "members": observed["members"],
        "type": observed["declared_type"],
        "unit": observed["unit"],
        "help": observed["help"],
        "observed_labels": observed["observed_labels"],
        "stored_labels": [],
        "match_keys": [],
        "population": "unknown",
        "lifecycle": "unknown",
        "availability": "OBSERVED",
        "cardinality_risk": "UNKNOWN",
        "evidence_refs": ["evidence/metric-facts.json"],
        "limitations": observed["warnings"][:6],
    }
    encoded = subprocess.run(
        ["yq", "eval", "-p=json", "-o=yaml", "."], input=json.dumps(record), capture_output=True, text=True, check=False
    )
    require(encoded.returncode == 0, "cannot encode checkpoint")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=output.parent, prefix=f".{record_id}.", delete=False) as draft:
        draft_path = Path(draft.name)
        draft.write(encoded.stdout)
    os.replace(draft_path, output)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("item", help="one filename from records/pending")
    parser.add_argument("record_id", help="shortlist ID, for example M001")
    parser.add_argument("category", nargs="?", choices=("BUSINESS", "PROCESS"), help="required unless the family has a pinned classification")
    args = parser.parse_args()
    try:
        output = create(args.item, args.record_id, args.category)
    except (OSError, json.JSONDecodeError, RecordError) as error:
        print(f"FAIL metric-record: {error}", file=sys.stderr)
        return 1
    print(f"PASS metric-record={output.relative_to(Path.cwd())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
