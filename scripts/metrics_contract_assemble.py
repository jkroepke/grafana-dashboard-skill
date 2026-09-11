#!/usr/bin/env python3
"""Assemble a metrics-contract draft from small metrics-review checkpoints."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import coordinator_stage as stage
import validate_workflow_artifact as workflow


class AssembleError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssembleError(message)


def records(directory: Path) -> list[dict[str, Any]]:
    if not directory.exists():
        return []
    require(directory.is_dir() and not directory.is_symlink(), f"checkpoint directory is invalid: {directory.name}")
    result: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.yaml")):
        require(path.is_file() and not path.is_symlink(), f"checkpoint is invalid: {path.name}")
        result.append(stage.read_yaml(path))
    return result


def assemble(agent_root: Path, ticket: dict[str, Any], unresolved: list[str]) -> dict[str, Any]:
    selector = agent_root / "records" / "selector-contract.yaml"
    require(selector.is_file() and not selector.is_symlink(), "write records/selector-contract.yaml first")
    require(len(unresolved) <= 12 and all(isinstance(item, str) and 0 < len(item) <= 256 and item.strip() for item in unresolved),
            "unresolved entries must be at most 12 non-empty strings of at most 256 characters")
    return {
        "schema_version": 1,
        "artifact_type": "metrics-contract",
        "run_id": ticket["run_id"],
        "revision": ticket["revision"],
        "inputs": {name: binding["sha256"] for name, binding in ticket["inputs"].items()},
        "status": "PASS",
        "approved": records(agent_root / "records" / "approved"),
        "rejected": records(agent_root / "records" / "rejected"),
        "not_considered": records(agent_root / "records" / "not-considered"),
        "selector_contract": stage.read_yaml(selector),
        "unresolved": unresolved,
    }


def write_draft(path: Path, payload: dict[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        require(path.is_file() and not path.is_symlink(), "metrics-contract draft is not a regular file")
        require(stage.read_yaml(path) == payload, "metrics-contract draft does not match checkpoints")
        return
    raw = stage.coordinator_artifact.yaml_bytes(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", dir=path.parent, prefix=f".{path.name}.", delete=False) as draft:
        draft_path = Path(draft.name)
        draft.write(raw)
    os.replace(draft_path, path)


def preflight_evidence(payload: dict[str, Any], agent_root: Path, run: dict[str, Any]) -> None:
    workflow.validate_evidence_references(payload, agent_root / "outbox" / "metrics-contract.yaml", run)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticket", type=Path, default=Path("inbox/job.yaml"), help="ticket; defaults to inbox/job.yaml")
    parser.add_argument("--unresolved", action="append", default=[], help="one bounded evidence gap; repeat as needed")
    args = parser.parse_args()
    try:
        ticket, run, _, _, _, _ = stage.validate_ticket(args.ticket)
        require(ticket["agent"] == "metrics-reviewer", "ticket is not for metrics-reviewer")
        agent_root = args.ticket.resolve().parent.parent
        payload = assemble(agent_root, ticket, args.unresolved)
        preflight_evidence(payload, agent_root, run)
        output = agent_root / "tmp" / "metrics-contract.yaml"
        write_draft(output, payload)
    except (OSError, AssembleError, workflow.ArtifactError, stage.StageError, stage.coordinator_artifact.CreationError, KeyError, TypeError) as error:
        print(f"FAIL metrics-contract-assemble: {error}", file=sys.stderr)
        return 1
    print(
        "PASS metrics-contract-assemble "
        f"approved={len(payload['approved'])} rejected={len(payload['rejected'])} "
        f"not_considered={len(payload['not_considered'])} unresolved={len(payload['unresolved'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
