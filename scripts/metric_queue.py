#!/usr/bin/env python3
"""Durably complete and reconcile metric-family queue items."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


class QueueError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise QueueError(message)


def workspace() -> tuple[Path, Path, Path, Path]:
    root = Path.cwd().resolve()
    pending = root / "records" / "pending"
    done = root / "records" / "done"
    state = root / "state.yaml"
    require(pending.is_dir() and done.is_dir() and state.is_file(),
            "run from an initialized metric-agent workspace")
    return root, pending, done, state


def read_state(path: Path) -> dict[str, object]:
    result = subprocess.run(["yq", "eval", "-o=json", ".", str(path)], capture_output=True, text=True, check=False)
    require(result.returncode == 0, "cannot read state.yaml")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise QueueError("cannot decode state.yaml") from error
    require(isinstance(value, dict), "state.yaml must contain an object")
    require(isinstance(value.get("pending"), list) and isinstance(value.get("completed"), list),
            "state.yaml queue fields are invalid")
    return value


def write_state(path: Path, state: dict[str, object]) -> None:
    result = subprocess.run(
        ["yq", "eval", "-p=json", "-o=yaml", "."],
        input=json.dumps(state, sort_keys=True), capture_output=True, text=True, check=False,
    )
    require(result.returncode == 0, "cannot encode state.yaml")
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=".state.", delete=False) as draft:
        draft_path = Path(draft.name)
        draft.write(result.stdout)
    os.replace(draft_path, path)


def complete(item_name: str, record: Path) -> None:
    root, pending, done, state_path = workspace()
    require(Path(item_name).name == item_name and item_name.endswith(".yaml"), "queue item must be one YAML filename")
    item = pending / item_name
    target = done / item_name
    require(item.is_file() and not item.is_symlink(), "queue item is unavailable")
    require(not target.exists(), "queue item is already complete")
    record_path = (root / record).resolve() if not record.is_absolute() else record.resolve()
    require(record_path.is_file() and not record_path.is_symlink(), "checkpoint record is unavailable")
    require(record_path.is_relative_to(root / "records"), "checkpoint record must be under records")
    state = read_state(state_path)
    pending_ref = f"records/pending/{item_name}"
    done_ref = f"records/done/{item_name}"
    record_ref = str(record_path.relative_to(root))
    state["pending"] = [value for value in state["pending"] if value != pending_ref]
    state["completed"] = list(dict.fromkeys([*state["completed"], record_ref, done_ref]))
    write_state(state_path, state)
    os.replace(item, target)
    print(f"PASS metric-queue complete={item_name}")


def reconcile() -> None:
    _, pending, done, state_path = workspace()
    state = read_state(state_path)
    completed = set(value for value in state["completed"] if isinstance(value, str))
    moved = 0
    for item in sorted(pending.glob("*.yaml")):
        if item.name == "manifest.yaml":
            continue
        if f"records/done/{item.name}" in completed:
            target = done / item.name
            require(not target.exists(), f"queue item exists in both pending and done: {item.name}")
            os.replace(item, target)
            moved += 1
    print(f"PASS metric-queue reconciled={moved}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("reconcile", help="move checkpointed items from pending to done")
    complete_parser = commands.add_parser("complete", help="checkpoint and complete one pending item")
    complete_parser.add_argument("item")
    complete_parser.add_argument("record", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "reconcile":
            reconcile()
        else:
            complete(args.item, args.record)
    except (OSError, QueueError) as error:
        print(f"FAIL metric-queue: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
