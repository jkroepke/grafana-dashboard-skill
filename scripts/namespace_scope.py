#!/usr/bin/env python3
"""Write immutable, canonical application namespace-scope evidence."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

import coordinator_stage as stage


def write(root: Path, values: list[str]) -> bool:
    namespaces = sorted(set(values))
    stage.require(namespaces and all(item for item in namespaces), "namespace scope must be a non-empty string array")
    output = root / "evidence" / "namespace-scope.json"
    if output.exists():
        stage.require(stage.read_namespace_scope(output) == namespaces, "namespace scope evidence is immutable")
        return False
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=output.parent, prefix=".namespace-scope.", delete=False) as draft:
        draft_path = Path(draft.name)
        draft.write(json.dumps(namespaces, separators=(",", ":")) + "\n")
    try:
        os.link(draft_path, output)
    except FileExistsError:
        stage.require(stage.read_namespace_scope(output) == namespaces, "namespace scope evidence is immutable")
        return False
    finally:
        draft_path.unlink(missing_ok=True)
    stage.read_namespace_scope(output)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("namespaces", nargs="+", help="verified namespace values")
    args = parser.parse_args()
    try:
        created = write(Path.cwd().resolve(), args.namespaces)
    except (OSError, stage.StageError) as error:
        print(f"FAIL namespace-scope: {error}", file=sys.stderr)
        return 1
    print(f"PASS namespace-scope namespaces={len(set(args.namespaces))} evidence=evidence/namespace-scope.json reused={str(not created).lower()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
