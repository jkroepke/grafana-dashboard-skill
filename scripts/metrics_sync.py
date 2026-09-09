#!/usr/bin/env python3
"""Create metric-family snapshots for an application-metrics ticket, or resume its queue."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import coordinator_stage as stage


SCRIPT_DIR = Path(__file__).resolve().parent
METRICS_READER = SCRIPT_DIR / "metrics_reader.py"
SNAPSHOT_METRICS = SCRIPT_DIR / "snapshot_metrics.py"
METRIC_QUEUE = SCRIPT_DIR / "metric_queue.py"


class SyncError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SyncError(message)


def queue_mode(pending: Path) -> str:
    """Return whether this is a new or resumable queue, rejecting unknown state."""
    if not pending.exists() and not pending.is_symlink():
        return "SNAPSHOT"
    require(pending.is_dir() and not pending.is_symlink(), "metric queue must be a regular directory")
    manifest = pending / "manifest.yaml"
    if manifest.exists():
        require(manifest.is_file() and not manifest.is_symlink(), "metric queue manifest must be regular")
        return "RESUME"
    require(not any(pending.iterdir()), "metric queue has files but no snapshot manifest")
    pending.rmdir()
    return "SNAPSHOT"


def snapshot(agent_root: Path, pending: Path) -> None:
    try:
        reader = subprocess.Popen(
            [sys.executable, str(METRICS_READER)],
            cwd=agent_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except OSError as error:
        raise SyncError("metrics reader could not start") from error
    require(reader.stdout is not None, "metrics reader has no stdout")
    try:
        parser = subprocess.run(
            [
                sys.executable,
                str(SNAPSHOT_METRICS),
                "--output-dir",
                str(pending),
                "--source-ref",
                "metrics-evidence",
            ],
            cwd=agent_root,
            stdin=reader.stdout,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    finally:
        reader.stdout.close()
    reader_returncode = reader.wait()
    require(reader_returncode == 0, "metrics acquisition failed")
    require(parser.returncode == 0, "metric snapshot failed")


def sync_workspace(agent_root: Path) -> str:
    pending = agent_root / "records" / "pending"
    mode = queue_mode(pending)
    if mode == "SNAPSHOT":
        snapshot(agent_root, pending)
        return "SNAPSHOT"
    result = subprocess.run(
        [sys.executable, str(METRIC_QUEUE), "reconcile"],
        cwd=agent_root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    require(result.returncode == 0, "metric queue reconciliation failed")
    return "RESUMED"


def sync(ticket_path: Path) -> str:
    ticket, _, _, _, _, _ = stage.validate_ticket(ticket_path)
    require(ticket["agent"] == "application-metrics", "ticket is not for application-metrics")
    return sync_workspace(ticket_path.resolve().parent.parent)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ticket",
        type=Path,
        default=Path("inbox/job.yaml"),
        help="ticket path; defaults to inbox/job.yaml in the agent workspace",
    )
    args = parser.parse_args()
    try:
        print(f"PASS metrics-sync {sync(args.ticket).lower()}")
    except (OSError, SyncError, stage.StageError, KeyError, TypeError) as error:
        print(f"FAIL metrics-sync: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
