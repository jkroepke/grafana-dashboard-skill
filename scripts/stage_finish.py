#!/usr/bin/env python3
"""Finish a specialist stage in one command.

For a normal stage, assemble the deterministic draft.  For a failure stage,
first create ``tmp/failure-report.yaml`` with ``stage-failure-report``.  This
command validates the draft, atomically promotes it, finalizes state, and emits
the only response the coordinator accepts.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import coordinator_stage as stage
import stage_assemble
import stage_check


def finish(ticket_path: Path) -> str:
    ticket, run, _, _, inputs, supports = stage.validate_ticket(ticket_path)
    root = ticket_path.resolve().parent.parent
    normal = root / ticket["outputs"]["artifact"]
    failure = root / ticket["outputs"]["failure_report"]
    stage.require(not normal.exists() and not failure.exists(), "stage output already exists")
    normal_draft = root / "tmp" / normal.name
    failure_draft = root / "tmp" / failure.name
    stage.require(not (normal_draft.exists() and failure_draft.exists()), "write at most one stage draft")
    if ticket["agent"] == "application-metrics":
        stage.read_namespace_scope(root / "evidence" / "namespace-scope.json")
    if not failure_draft.exists() and not normal_draft.exists():
        stage_assemble.write_draft(normal_draft, stage_assemble.assemble(root, ticket, run, inputs))
    draft = stage_check.validate_draft(ticket, inputs, supports, root)
    output = failure if draft == failure_draft else normal
    os.replace(draft, output)
    return stage_check.terminal_response(ticket, inputs, supports, root)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticket", type=Path, default=Path("inbox/job.yaml"), help="ticket; defaults to inbox/job.yaml")
    args = parser.parse_args()
    try:
        print(finish(args.ticket))
    except (OSError, stage.StageError, stage_assemble.AssembleError, KeyError, TypeError) as error:
        print(f"FAIL stage-finish: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
