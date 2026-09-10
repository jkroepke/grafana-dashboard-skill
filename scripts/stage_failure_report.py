#!/usr/bin/env python3
"""Write a bounded specialist failure report from the validated local ticket."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

import coordinator_stage as stage
import stage_finish


class FailureError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise FailureError(message)


def write_draft(path: Path, payload: dict) -> None:
    raw = stage.coordinator_artifact.yaml_bytes(payload)
    if path.exists() or path.is_symlink():
        require(path.is_file() and not path.is_symlink() and path.read_bytes() == raw,
                "failure draft does not match the requested report")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", dir=path.parent, prefix=f".{path.name}.", delete=False) as file:
        temporary = Path(file.name)
        file.write(raw)
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticket", type=Path, default=Path("inbox/job.yaml"), help="ticket; defaults to inbox/job.yaml")
    parser.add_argument("--status", choices=("FAIL", "BLOCKED"), required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--code", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--evidence", action="append", default=[])
    parser.add_argument("--finish", action="store_true", help="validate, promote, and return the terminal response")
    args = parser.parse_args()
    try:
        ticket, _, _, _, _, _ = stage.validate_ticket(args.ticket)
        root = args.ticket.resolve().parent.parent
        require(len(args.evidence) <= 3, "at most three evidence paths are allowed")
        evidence: list[str] = []
        for item in args.evidence:
            path = (root / item).resolve()
            require(path.is_file() and not path.is_symlink(), f"evidence is not a regular file: {item}")
            require(path.is_relative_to(root), f"evidence escapes agent workspace: {item}")
            evidence.append(str(path.relative_to(root)))
        payload = {
            "schema_version": 1, "artifact_type": "failure-report", "run_id": ticket["run_id"],
            "revision": ticket["revision"], "inputs": {"run-contract": ticket["inputs"]["run-contract"]["sha256"]},
            "status": args.status, "failed_stage": ticket["agent"], "owner": args.owner,
            "code": args.code, "summary": args.summary, "evidence_refs": evidence,
        }
        write_draft(root / "tmp" / "failure-report.yaml", payload)
    except (OSError, FailureError, stage.StageError, stage.coordinator_artifact.CreationError, KeyError, TypeError) as error:
        print(f"FAIL stage-failure-report: {error}", file=sys.stderr)
        return 1
    if args.finish:
        try:
            print(stage_finish.finish(args.ticket))
        except (OSError, stage.StageError, stage_finish.stage_assemble.AssembleError, KeyError, TypeError) as error:
            print(f"FAIL stage-failure-report: {error}", file=sys.stderr)
            return 1
    else:
        print("PASS stage-failure-report draft=tmp/failure-report.yaml")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
