#!/usr/bin/env python3
"""Promote one model-authored PromQL record request to its fixed YAML checkpoint."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import coordinator_stage as stage


class QueryRecordError(ValueError):
    pass


FIELDS = {
    "id", "role", "consumer_id", "consumer_locator", "plugin_query_model", "question_id", "metric_ids", "language",
    "expression", "mode", "datasource_ref", "unit", "result_identity", "no_data_semantics",
    "expected_cardinality", "assumptions", "edge_cases", "change", "validation",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise QueryRecordError(message)


def read_request(path: Path, root: Path) -> dict[str, Any]:
    """Read one complete JSON record request from the agent scratch directory."""
    request = path.resolve()
    scratch = (root / "tmp").resolve()
    require(request.is_relative_to(scratch), "record request must be under tmp/")
    require(request.is_file() and not request.is_symlink(), "record request must be a regular JSON file")
    try:
        value = json.loads(request.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise QueryRecordError("record request must be a JSON object") from error
    require(isinstance(value, dict) and set(value) == FIELDS, "record request has missing or unknown fields")
    return value


def write_record(root: Path, request: Path) -> Path:
    """Serialize one complete request at records/queries/<id>.yaml."""
    record = read_request(request, root)
    query_id = record["id"]
    require(isinstance(query_id, str) and stage.SAFE_LIMIT_RE.fullmatch(query_id) is not None,
            "record id is invalid")
    output = root / "records" / "queries" / f"{query_id}.yaml"
    stage.atomic_yaml(output, record, replace=True)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", type=Path, help="complete JSON record request under tmp/")
    parser.add_argument("--ticket", type=Path, default=Path("inbox/job.yaml"), help="ticket; defaults to inbox/job.yaml")
    args = parser.parse_args()
    try:
        ticket, _, _, _, _, _ = stage.validate_ticket(args.ticket)
        require(ticket["agent"] == "promql-builder", "ticket is not for promql-builder")
        root = args.ticket.resolve().parent.parent
        output = write_record(root, args.request)
    except (OSError, QueryRecordError, stage.StageError, KeyError, TypeError) as error:
        print(f"FAIL query-record: {error}", file=sys.stderr)
        return 1
    print(f"PASS query-record record={output.relative_to(root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
