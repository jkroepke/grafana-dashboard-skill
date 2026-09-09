#!/usr/bin/env python3
"""Verify or promote the canonical artifact chain for the active workspace run."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from grafana_access import grafana_env


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--promote", action="store_true")
    args = parser.parse_args()
    workspace = Path.cwd().resolve()
    if workspace.name != "workspace" or workspace.parent.parent.name != "dashboards":
        print("FAIL workflow-chain: run from dashboards/<project-name>/workspace", file=sys.stderr)
        return 1
    run_id = grafana_env(workspace / ".env").get("WORKFLOW_RUN_ID")
    if not run_id:
        print("FAIL workflow-chain: WORKFLOW_RUN_ID is unavailable", file=sys.stderr)
        return 1
    root = workspace.parents[2]
    paths = {
        "run": workspace / "coordinator" / run_id / "outbox" / "run-contract.yaml",
        "application": workspace / "application-metrics" / run_id / "outbox" / "application-metrics.yaml",
        "kubernetes": workspace / "kubernetes-metrics" / run_id / "outbox" / "kubernetes-metrics.yaml",
        "metrics": workspace / "metrics-reviewer" / run_id / "outbox" / "metrics-contract.yaml",
        "plan": workspace / "dashboard-architect" / run_id / "outbox" / "dashboard-plan.yaml",
        "pack": workspace / "promql-builder" / run_id / "outbox" / "query-pack.yaml",
        "review": workspace / "promql-reviewer" / run_id / "outbox" / "query-review.yaml",
        "build": workspace / "dashboard-builder" / run_id / "outbox" / "dashboard-build.yaml",
        "dashboard_review": workspace / "dashboard-reviewer" / run_id / "outbox" / "dashboard-review.yaml",
    }
    command = [
        sys.executable, str(Path(__file__).with_name("verify_workflow_chain.py")),
        *(str(paths[name]) for name in ("run", "metrics", "plan", "pack", "review", "build", "dashboard_review")),
        "--application-metrics", str(paths["application"]),
    ]
    if paths["kubernetes"].is_file():
        command.extend(["--kubernetes-metrics", str(paths["kubernetes"])])
    if args.promote:
        command.append("--promote")
    result = subprocess.run(command, cwd=root, check=False)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
