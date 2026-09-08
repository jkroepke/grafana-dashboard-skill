#!/usr/bin/env python3
"""Re-render a dashboard source with the run-contract argv and verify exact output."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import validate_workflow_artifact as artifact


class RenderError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RenderError(message)


def render_source(run: dict[str, Any], source_path: Path) -> bytes:
    require(source_path.is_file() and not source_path.is_symlink(),
            "render source must be a regular non-symlink file")
    source_raw = source_path.read_bytes()
    require(len(source_raw) <= 4 * 1024 * 1024, "dashboard source exceeds 4 MiB")
    require(b"std.thisFile" not in source_raw,
            "dashboard source must not depend on std.thisFile")

    render = run["render"]
    argv = [str(source_path) if item == "{source}" else item for item in render["argv"]]
    try:
        result = subprocess.run(
            argv,
            cwd=render["cwd"],
            capture_output=True,
            check=False,
            timeout=render["timeout_seconds"],
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RenderError(f"render command could not complete ({type(error).__name__})") from error
    require(result.returncode == 0, f"render command failed with exit code {result.returncode}")
    require(len(result.stdout) <= 16 * 1024 * 1024, "rendered dashboard exceeds 16 MiB")
    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RenderError("render command did not produce valid JSON") from error
    require(isinstance(parsed, dict), "rendered dashboard root must be an object")
    return result.stdout


def verify(run: dict[str, Any], build: dict[str, Any], source_path: Path | None = None) -> bytes:
    if source_path is None:
        source = Path(build["candidate_path"])
    else:
        source = source_path
        require(source.resolve(strict=False) == Path(run["source"]["final_path"]).resolve(strict=False),
                "explicit render source must be the promoted final source")
    rendered = Path(build["rendered_path"])
    require(rendered.is_file() and not rendered.is_symlink(),
            "recorded render must be a regular non-symlink file")
    require(
        artifact.sha256_bytes(source.read_bytes()) == build["candidate_sha256"],
        "render source digest is not the reviewed candidate digest",
    )
    actual = render_source(run, source)
    recorded = rendered.read_bytes()
    require(actual == recorded, "recorded render is not the exact output of the dashboard source")
    require(artifact.sha256_bytes(actual) == build["rendered_sha256"],
            "recorded render digest mismatch")
    return actual


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_contract", type=Path)
    parser.add_argument("dashboard_build", type=Path)
    parser.add_argument("--source", type=Path)
    args = parser.parse_args()
    try:
        run_raw, run = artifact.read_artifact(args.run_contract)
        artifact.validate_artifact(run, len(run_raw), {}, args.run_contract)
        build_raw, build = artifact.read_artifact(args.dashboard_build)
        artifact.validate_envelope(build, len(build_raw))
        require(build["inputs"].get("run-contract") == artifact.sha256_bytes(run_raw),
                "dashboard build does not bind the supplied run contract")
        rendered_raw = verify(run, build, args.source)
    except (artifact.ArtifactError, RenderError, KeyError, OSError, TypeError) as error:
        print(f"FAIL {error}", file=sys.stderr)
        return 1
    print(f"PASS candidate render {artifact.sha256_bytes(rendered_raw)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
