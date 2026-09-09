#!/usr/bin/env python3
"""Run the fixed dashboard integrity checks for one validated specialist ticket."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import coordinator_stage as stage
import validate_workflow_artifact as artifact
import verify_candidate_render as candidate_render
import verify_dashboard_contract as dashboard_contract
import verify_non_prometheus_preservation as non_prometheus
import verify_query_parity as query_parity


class IntegrityError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise IntegrityError(message)


def read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as error:
        raise IntegrityError(f"cannot read {label}") from error
    require(isinstance(value, dict), f"{label} must be a JSON object")
    return value


def regular(path: Path, label: str) -> None:
    require(path.is_file() and not path.is_symlink(), f"{label} must be a regular file")


def rendered_for_builder(ticket: dict[str, Any], run: dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
    candidate = Path(ticket["outputs"]["candidate"])
    rendered = Path(ticket["outputs"]["rendered"])
    require(candidate == Path(run["source"]["candidate_path"]), "ticket candidate path is invalid")
    regular(candidate, "candidate source")
    regular(rendered, "recorded render")
    actual = candidate_render.render_source(run, candidate)
    require(actual == rendered.read_bytes(), "recorded render is not the exact candidate output")
    return actual, read_json(rendered, "recorded render")


def rendered_for_existing(run: dict[str, Any], build_path: Path, final: bool) -> tuple[bytes, dict[str, Any]]:
    _, build = artifact.read_artifact(build_path)
    source = Path(run["source"]["final_path"]) if final else None
    actual = candidate_render.verify(run, build, source)
    return actual, json.loads(actual)


def baseline(run: dict[str, Any]) -> dict[str, Any] | None:
    source = run["source"]
    final = Path(source["final_path"])
    if source["baseline_state"] == "ABSENT":
        require(not final.exists(), "final source appeared after the absent baseline")
        return None
    regular(final, "baseline source")
    require(artifact.sha256_bytes(final.read_bytes()) == source["baseline_sha256"],
            "baseline source changed after capture")
    return read_json_bytes(candidate_render.render_source(run, final), "baseline render")


def read_json_bytes(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise IntegrityError(f"cannot read {label}") from error
    require(isinstance(value, dict), f"{label} must be a JSON object")
    return value


def check(ticket_path: Path) -> None:
    ticket, run, _, _, inputs, supports = stage.validate_ticket(ticket_path)
    bindings = {**inputs, **supports}
    agent = ticket["agent"]
    require(agent in {"dashboard-builder", "dashboard-reviewer", "dashboard-publisher"},
            "dashboard integrity is only available to dashboard stages")

    if agent == "dashboard-builder":
        _, rendered = rendered_for_builder(ticket, run)
    else:
        _, rendered = rendered_for_existing(run, inputs["dashboard-build"], agent == "dashboard-publisher")

    dashboard_contract.verify(rendered)
    pack = stage.read_yaml(bindings["query-pack"])
    expected, _ = query_parity.approved_consumers(pack)
    require(expected == query_parity.v2_consumers(rendered), "approved/rendered query parity failed")
    if agent != "dashboard-publisher":
        non_prometheus.verify(rendered, baseline(run))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticket", required=True, type=Path)
    args = parser.parse_args()
    try:
        check(args.ticket)
    except (
        stage.StageError,
        artifact.ArtifactError,
        candidate_render.RenderError,
        dashboard_contract.ContractError,
        non_prometheus.PreservationError,
        query_parity.ParityError,
        IntegrityError,
        KeyError,
        OSError,
        TypeError,
    ) as error:
        print(f"FAIL dashboard-integrity: {error}", file=sys.stderr)
        return 1
    print("PASS dashboard-integrity")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
