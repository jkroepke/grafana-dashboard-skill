#!/usr/bin/env python3
"""Validate one specialist output using only its immutable ticket."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import coordinator_stage as stage


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticket", required=True, type=Path)
    args = parser.parse_args()
    try:
        ticket, _, _, _, inputs, supports = stage.validate_ticket(args.ticket)
        agent_root = args.ticket.resolve().parent.parent
        normal = agent_root / ticket["outputs"]["artifact"]
        failure = agent_root / ticket["outputs"]["failure_report"]
        candidates = [path for path in (normal, failure) if path.is_file() and not path.is_symlink()]
        stage.require(len(candidates) == 1, "write exactly one assigned stage artifact")
        artifact = candidates[0]
        stage.validate_artifact_file(artifact, {**inputs, **supports})
        data = stage.read_yaml(artifact)
        status = data["status"]
        expected = "DONE" if ticket["agent"] in {"application-metrics", "kubernetes-metrics"} else "PASS"
        if artifact == normal:
            stage.require(status == expected, "normal artifact has an invalid status")
            field = "artifact"
        else:
            stage.require(status in {"FAIL", "BLOCKED"}, "failure report has an invalid status")
            field = "report"
        stage.coordinator_artifact.validate_workspace(agent_root)
        print(f"{status} {ticket['agent']} {field}={artifact.relative_to(agent_root)} sha256={stage.sha256(artifact)}")
    except (stage.StageError, OSError, KeyError) as error:
        print(f"FAIL stage-check: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
