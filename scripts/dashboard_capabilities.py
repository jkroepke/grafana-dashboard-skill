#!/usr/bin/env python3
"""Emit the planning-relevant approved metric capabilities for dashboard architecture."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import coordinator_stage as stage


class CapabilityError(ValueError):
    pass


FIELDS = (
    "id", "source_artifact", "source_metric_id", "source", "category", "family", "type", "unit",
    "semantics", "lifecycle", "identity_labels", "bounded_dimensions", "availability", "allowed_use", "risks",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CapabilityError(message)


def emit(contract_path: Path, output: Path) -> dict[str, Any]:
    contract = stage.read_yaml(contract_path)
    approved = contract.get("approved") if isinstance(contract, dict) else None
    require(isinstance(approved, list), "metrics contract approved capabilities are unavailable")
    capabilities: list[dict[str, Any]] = []
    for record in approved:
        require(isinstance(record, dict) and set(FIELDS) <= set(record), "approved capability is incomplete")
        capabilities.append({field: record[field] for field in FIELDS})
    capabilities.sort(key=lambda item: item["id"])
    totals = Counter(item["allowed_use"] for item in capabilities)
    payload = {
        "schema_version": 1,
        "kind": "dashboard-capabilities",
        "metrics_contract_sha256": "sha256:" + hashlib.sha256(contract_path.read_bytes()).hexdigest(),
        "totals": {"approved": len(capabilities), "plan": totals["PLAN"], "preserve_only": totals["PRESERVE_ONLY"]},
        "question_contract": {
            "required_fields": ["id", "text", "priority", "category", "metric_ids", "calculation", "result_shape", "retained_labels", "row_identity_labels", "no_data_requirement", "change"],
            "priority": ["MUST", "SHOULD"],
            "category": ["BUSINESS", "PROCESS", "KUBERNETES"],
            "result_shape": ["SCALAR", "TIME_SERIES", "LABEL_SET", "DISTRIBUTION"],
            "change": ["NEW", "MODIFIED", "PRESERVED"],
        },
        "capabilities": capabilities,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    require(len(encoded.encode()) <= 64 * 1024, "capability summary exceeds 64 KiB")
    if output.exists() or output.is_symlink():
        require(output.is_file() and not output.is_symlink(), "capability summary is not a regular file")
        try:
            existing = json.loads(output.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise CapabilityError("capability summary is invalid") from error
        require(existing == payload, "capability summary does not match the metrics contract")
        return payload
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(encoded, encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticket", type=Path, default=Path("inbox/job.yaml"), help="ticket; defaults to inbox/job.yaml")
    parser.add_argument("--output", type=Path, default=Path("evidence/approved-capabilities.json"))
    args = parser.parse_args()
    try:
        ticket, _, _, _, inputs, _ = stage.validate_ticket(args.ticket)
        require(ticket["agent"] == "dashboard-architect", "ticket is not for dashboard-architect")
        payload = emit(inputs["metrics-contract"], args.output)
    except (OSError, CapabilityError, stage.StageError, KeyError, TypeError) as error:
        print(f"FAIL dashboard-capabilities: {error}", file=sys.stderr)
        return 1
    print(f"PASS dashboard-capabilities approved={payload['totals']['approved']} plan={payload['totals']['plan']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
