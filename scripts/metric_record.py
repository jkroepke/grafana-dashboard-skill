#!/usr/bin/env python3
"""Create one application-metric checkpoint from an observed snapshot."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from metric_facts import pinned_classification


class RecordError(ValueError):
    pass


SNAPSHOT_ID = re.compile(r"^F[0-9]{5}$")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RecordError(message)


def yaml_object(path: Path) -> dict[str, Any]:
    result = subprocess.run(["yq", "eval", "-o=json", ".", str(path)], capture_output=True, text=True, check=False)
    require(result.returncode == 0, f"cannot read snapshot {path.name}")
    value = json.loads(result.stdout)
    require(isinstance(value, dict) and value.get("kind") == "metric-family-snapshot", "input is not a metric snapshot")
    return value


def discovery_labels(root: Path, snapshot_id: str) -> tuple[list[str], str]:
    require(SNAPSHOT_ID.fullmatch(snapshot_id) is not None, "snapshot ID must look like F00001")
    reference = f"evidence/metric-discovery/responses/{snapshot_id}.json"
    path = root / reference
    require(path.is_file() and not path.is_symlink(), "stored-series discovery response is unavailable")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RecordError("stored-series discovery response is invalid") from error
    values = payload.get("data") if isinstance(payload, dict) and payload.get("status") == "success" else []
    require(isinstance(values, list), "stored-series discovery response is invalid")
    return sorted({key for value in values if isinstance(value, dict) for key in value if isinstance(key, str)}), reference


def record_id_for(snapshot_id: str) -> str:
    require(SNAPSHOT_ID.fullmatch(snapshot_id) is not None, "snapshot ID must look like F00001")
    return f"M{int(snapshot_id[1:]):05d}"


def create(item: str, category: str | None) -> Path:
    root = Path.cwd().resolve()
    pending = root / "records" / "pending"
    require((root / "records" / "done").is_dir() and (root / "state.yaml").is_file(), "run from an initialized metric-agent workspace")
    require(Path(item).name == item and item.endswith(".yaml") and item != "manifest.yaml", "item must be one pending YAML filename")
    snapshot = pending / item
    require(snapshot.is_file() and not snapshot.is_symlink(), "pending snapshot is unavailable")
    observed = yaml_object(snapshot)
    known = pinned_classification(observed)
    if known:
        require(category in {None, known[0]}, f"pinned family category is {known[0]}")
        category = known[0]
    require(category in {"BUSINESS", "PROCESS"}, "category BUSINESS or PROCESS is required for an unclassified family")
    snapshot_id = observed.get("id")
    require(isinstance(snapshot_id, str), "snapshot ID is unavailable")
    record_id = record_id_for(snapshot_id)
    stored_labels, discovery_ref = discovery_labels(root, snapshot_id)
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
        "stored_labels": stored_labels,
        "match_keys": [],
        "population": "unknown",
        "lifecycle": "unknown",
        "availability": "OBSERVED",
        "cardinality_risk": "UNKNOWN",
        "evidence_refs": ["evidence/metric-facts.json", discovery_ref],
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
    parser.add_argument("category", nargs="?", choices=("BUSINESS", "PROCESS"), help="required unless the family has a pinned classification")
    args = parser.parse_args()
    try:
        output = create(args.item, args.category)
    except (OSError, json.JSONDecodeError, RecordError) as error:
        print(f"FAIL metric-record: {error}", file=sys.stderr)
        return 1
    print(f"PASS metric-record pending={args.item} record={output.relative_to(Path.cwd())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
