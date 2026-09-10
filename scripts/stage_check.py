#!/usr/bin/env python3
"""Validate a specialist draft or terminal output using only its immutable ticket."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import coordinator_stage as stage


def expected_status(agent: str) -> str:
    return "DONE" if agent in {"application-metrics", "kubernetes-metrics"} else "PASS"


def validate_draft(
    ticket: dict,
    inputs: dict[str, Path],
    supports: dict[str, Path],
    agent_root: Path,
) -> Path:
    normal = agent_root / ticket["outputs"]["artifact"]
    failure = agent_root / ticket["outputs"]["failure_report"]
    stage.require(not normal.exists() and not failure.exists(),
                  "move no artifact to outbox before draft validation")
    normal_draft = agent_root / "tmp" / normal.name
    failure_draft = agent_root / "tmp" / failure.name
    candidates = [path for path in (normal_draft, failure_draft) if path.is_file() and not path.is_symlink()]
    stage.require(len(candidates) == 1, "write exactly one assigned stage draft")
    draft = candidates[0]
    output = failure if draft == failure_draft else normal
    validation_path = output.parent / f".{output.stem}.draft-check.yaml"
    stage.require(not os.path.lexists(validation_path), "draft validation path already exists")
    try:
        os.link(draft, validation_path)
        stage.validate_artifact_file(validation_path, {**inputs, **supports})
    finally:
        if os.path.lexists(validation_path):
            validation_path.unlink()
    data = stage.read_yaml(draft)
    if output == normal:
        stage.require(data["status"] == expected_status(ticket["agent"]),
                      "draft artifact has an invalid status")
    else:
        stage.require(data["status"] in {"FAIL", "BLOCKED"}, "failure report has an invalid status")
    return draft


def finalize_state(agent_root: Path, artifact: Path, status: str) -> None:
    """Apply the one terminal state transition after artifact validation."""
    state_path = agent_root / "state.yaml"
    state = stage.read_yaml(state_path)
    completed = state.get("completed")
    stage.require(isinstance(completed, list) and all(isinstance(item, str) for item in completed),
                  "state.yaml completed must be a list of paths")
    artifact_ref = str(artifact.relative_to(agent_root))
    completed = list(dict.fromkeys([*completed, artifact_ref]))
    stage.run_yq_update(
        state_path,
        '.status = strenv(TERMINAL_STATUS) | .completed = (strenv(COMPLETED_JSON) | from_json) | '
        '.pending = [] | .next_action = "complete"',
        {"TERMINAL_STATUS": status, "COMPLETED_JSON": json.dumps(completed)},
    )


def terminal_response(ticket: dict, inputs: dict[str, Path], supports: dict[str, Path], agent_root: Path) -> str:
    """Validate the single promoted output, finalize state, and return its wire response."""
    normal = agent_root / ticket["outputs"]["artifact"]
    failure = agent_root / ticket["outputs"]["failure_report"]
    candidates = [path for path in (normal, failure) if path.is_file() and not path.is_symlink()]
    stage.require(len(candidates) == 1, "write exactly one assigned stage artifact")
    artifact = candidates[0]
    stage.validate_artifact_file(artifact, {**inputs, **supports})
    data = stage.read_yaml(artifact)
    status = data["status"]
    expected = expected_status(ticket["agent"])
    if artifact == normal:
        stage.require(status == expected, "normal artifact has an invalid status")
        field = "artifact"
    else:
        stage.require(status in {"FAIL", "BLOCKED"}, "failure report has an invalid status")
        field = "report"
    finalize_state(agent_root, artifact, status)
    stage.coordinator_artifact.validate_workspace(agent_root)
    return f"{status} {ticket['agent']} {field}={artifact.relative_to(agent_root)} sha256={stage.sha256(artifact)}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticket", type=Path, default=Path("inbox/job.yaml"))
    parser.add_argument("--draft", action="store_true",
                        help="validate tmp/<assigned artifact name> before moving it to outbox")
    args = parser.parse_args()
    try:
        ticket, _, _, _, inputs, supports = stage.validate_ticket(args.ticket)
        agent_root = args.ticket.resolve().parent.parent
        if args.draft:
            draft = validate_draft(ticket, inputs, supports, agent_root)
            print(f"PASS {ticket['agent']} draft={draft.relative_to(agent_root)}")
            return 0
        print(terminal_response(ticket, inputs, supports, agent_root))
    except (stage.StageError, OSError, KeyError) as error:
        print(f"FAIL stage-check: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
