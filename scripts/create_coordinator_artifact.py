#!/usr/bin/env python3
"""Create deterministic coordinator artifacts and keep coordinator state consistent."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


SCRIPT_DIR = Path(__file__).resolve().parent
INIT_WORKSPACE = SCRIPT_DIR / "init_agent_workspace.sh"
VALIDATOR = SCRIPT_DIR / "validate_workflow_artifact.py"
WORKSPACE_VALIDATOR = SCRIPT_DIR / "validate_agent_workspace.sh"
HARD_LIMITS = {
    "approved_metrics": 40,
    "changed_questions": 12,
    "changed_panels": 12,
    "changed_queries": 24,
    "total_panels": 48,
    "total_queries": 64,
    "findings": 20,
}
SAFE_COMPONENT_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
PROMETHEUS_LABEL_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class CreationError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CreationError(message)


def sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def repository_path(root: Path, value: str, label: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise CreationError(f"{label} must be inside repository root") from error
    return resolved


def evidence_reference(root: Path, value: str, label: str) -> str:
    raw_path = value.split("#", 1)[0]
    line_match = re.fullmatch(r"(.+):([1-9][0-9]*)", raw_path)
    if line_match is not None:
        raw_path = line_match.group(1)
    path = repository_path(root, raw_path, label)
    require(path.is_file() and not path.is_symlink(), f"{label} must identify a regular file")
    return str(path)


def grafonnet_dependencies(root: Path) -> list[tuple[str, Path]]:
    lock_path = root / "jsonnetfile.lock.json"
    if not lock_path.is_file():
        return []
    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CreationError(f"cannot read {lock_path}: {error}") from error

    dependencies: list[tuple[str, Path]] = []
    for item in lock.get("dependencies", []):
        git = item.get("source", {}).get("git", {})
        remote = git.get("remote")
        revision = item.get("version")
        if not isinstance(remote, str) or not isinstance(revision, str):
            continue
        parsed = urlparse(remote)
        normalized = f"{parsed.netloc}{parsed.path}".removesuffix(".git").strip("/")
        if normalized != "github.com/grafana/grafonnet":
            continue
        subdir = git.get("subdir", "")
        require(isinstance(subdir, str), "Grafonnet lock subdir must be a string")
        dependencies.append((revision, root / "vendor" / normalized / subdir))
    return dependencies


def infer_grafonnet_revision(root: Path, requested: str | None) -> str | None:
    dependencies = grafonnet_dependencies(root)
    if requested is not None:
        if dependencies:
            matches = [path for revision, path in dependencies if revision == requested]
            require(matches, "requested Grafonnet revision is not present in jsonnetfile.lock.json")
            require(any(path.is_dir() for path in matches), "requested Grafonnet revision is not vendored locally")
        return requested
    if not dependencies:
        return None
    revisions = {revision for revision, _ in dependencies}
    require(len(revisions) == 1, "multiple Grafonnet revisions are locked; pass --grafonnet-revision")
    revision = next(iter(revisions))
    require(
        any(path.is_dir() for locked_revision, path in dependencies if locked_revision == revision),
        "locked Grafonnet revision is not vendored locally",
    )
    return revision


def render_executable(root: Path, program: str) -> str:
    if "/" in program:
        candidate = Path(program)
        if not candidate.is_absolute():
            candidate = root / candidate
        require(candidate.is_file() and os.access(candidate, os.X_OK), "render program is not executable")
        return str(candidate.resolve()) if Path(program).is_absolute() else program
    require(shutil.which(program) is not None, f"render program is unavailable: {program}")
    return program


def yaml_bytes(value: dict[str, Any]) -> bytes:
    try:
        result = subprocess.run(
            ["yq", "eval", "-p=json", "-o=yaml", "."],
            input=json.dumps(value, sort_keys=True),
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as error:
        raise CreationError("Mike Farah yq v4 is required") from error
    require(result.returncode == 0, result.stderr.strip() or "yq could not serialize artifact")
    return result.stdout.encode("utf-8")


def initialize_coordinator(root: Path, project: str, run_id: str) -> Path:
    result = subprocess.run(
        [str(INIT_WORKSPACE), str(root), project, run_id, "coordinator"],
        capture_output=True,
        text=True,
        check=False,
    )
    require(result.returncode == 0, result.stderr.strip() or "could not initialize coordinator workspace")
    return Path(result.stdout.strip())


def validate_artifact(root: Path, path: Path, inputs: list[str] | None = None) -> str:
    command = [sys.executable, str(VALIDATOR), str(path)]
    for binding in inputs or []:
        command.extend(["--input", binding])
    result = subprocess.run(command, cwd=root, capture_output=True, text=True, check=False)
    require(result.returncode == 0, result.stderr.strip() or "artifact validation failed")
    return result.stdout.strip()


def validate_workspace(path: Path) -> None:
    result = subprocess.run(
        [str(WORKSPACE_VALIDATOR), str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    require(result.returncode == 0, result.stderr.strip() or "coordinator workspace validation failed")


def promote_immutable(output: Path, raw: bytes, root: Path, inputs: list[str] | None = None) -> str:
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        require(output.is_file() and not output.is_symlink(), f"artifact is not a regular file: {output}")
        require(output.read_bytes() == raw, f"refusing to replace immutable artifact: {output}")
        return validate_artifact(root, output, inputs)

    draft = output.parent / f".{output.stem}.{os.getpid()}.yaml"
    require(not draft.exists(), f"temporary artifact already exists: {draft}")
    try:
        draft.write_bytes(raw)
        validation = validate_artifact(root, draft, inputs)
        try:
            os.link(draft, output)
        except FileExistsError:
            require(
                output.is_file() and not output.is_symlink() and output.read_bytes() == raw,
                f"refusing to replace immutable artifact: {output}",
            )
    finally:
        if draft.exists():
            draft.unlink()
    return validation


def update_state(state_path: Path, *, status: str, completed: str, pending: list[str], next_action: str) -> None:
    environment = os.environ.copy()
    environment.update({
        "STATE_STATUS": status,
        "COMPLETED_REF": completed,
        "PENDING_JSON": json.dumps(pending),
        "NEXT_ACTION": next_action,
    })
    expression = (
        '.status = strenv(STATE_STATUS) | '
        '.completed = ((.completed // []) + [strenv(COMPLETED_REF)] | unique) | '
        '.pending = (strenv(PENDING_JSON) | from_json) | '
        '.next_action = strenv(NEXT_ACTION)'
    )
    result = subprocess.run(
        ["yq", "eval", "-i", expression, str(state_path)],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    require(result.returncode == 0, result.stderr.strip() or "could not update coordinator state")


def create_run_contract(args: argparse.Namespace) -> str:
    root = Path(args.repository_root).resolve()
    require(root.is_dir() and not root.is_symlink(), "repository root must be a regular directory")
    require(SAFE_COMPONENT_RE.fullmatch(args.project_name) is not None, "project name is not filesystem-safe")
    require(SAFE_COMPONENT_RE.fullmatch(args.run_id) is not None, "run ID is not filesystem-safe")

    coordinator = initialize_coordinator(root, args.project_name, args.run_id)
    workspace = root / "dashboards" / args.project_name / "workspace"
    final_source = repository_path(root, args.final_source, "final source")
    candidate = final_source.with_name(f"{final_source.stem}.candidate.jsonnet")
    if final_source.exists():
        require(final_source.is_file() and not final_source.is_symlink(), "final source must be a regular file")
        baseline_state = "PRESENT"
        baseline_sha256 = sha256(final_source)
    else:
        baseline_state = "ABSENT"
        baseline_sha256 = None

    program = render_executable(root, args.render_program)
    render_args = args.render_arg or ["-J", "vendor", "{source}"]
    render_argv = [program, *render_args]
    require(render_argv.count("{source}") == 1, "render arguments require one standalone {source}")
    grafonnet_revision = infer_grafonnet_revision(root, args.grafonnet_revision)
    for name, label in {
        "application namespace label": args.application_namespace_label,
        "application pod label": args.application_pod_label,
        "Kubernetes namespace label": args.kubernetes_namespace_label,
        "Kubernetes pod label": args.kubernetes_pod_label,
        "cluster label": args.cluster_label,
    }.items():
        require(label is None or PROMETHEUS_LABEL_RE.fullmatch(label) is not None,
                f"{name} is not a Prometheus label name")

    artifact = {
        "schema_version": 1,
        "artifact_type": "run-contract",
        "run_id": args.run_id,
        "revision": 1,
        "inputs": {},
        "status": "PASS",
        "repository_root": str(root),
        "workspace": str(workspace),
        "source": {
            "final_path": str(final_source),
            "candidate_path": str(candidate),
            "baseline_state": baseline_state,
            "baseline_sha256": baseline_sha256,
        },
        "rendered_candidate_path": str(
            workspace / "dashboard-builder" / args.run_id / "evidence" / "rendered.json"
        ),
        "render": {"cwd": str(root), "argv": render_argv, "timeout_seconds": args.timeout_seconds},
        "schema": {
            "dashboard": args.schema,
            "grafana_version": args.grafana_version,
            "grafonnet_revision": grafonnet_revision,
        },
        "limits": HARD_LIMITS,
        "capabilities": {
            "datasource_access": args.datasource_access,
            "dashboard_api_validation": args.dashboard_api_validation,
            "publish_requested": args.publish_requested,
        },
        "selector_proposals": {
            "application_namespace_label": args.application_namespace_label,
            "application_pod_label": args.application_pod_label,
            "kubernetes_namespace_label": args.kubernetes_namespace_label,
            "kubernetes_pod_label": args.kubernetes_pod_label,
            "cluster_label": args.cluster_label,
            "fixed_selector_refs": [
                evidence_reference(root, value, "fixed selector reference")
                for value in args.fixed_selector_ref
            ],
            "population_refs": [
                evidence_reference(root, value, "population reference")
                for value in args.population_ref
            ],
            "scrape_interval_ref": (
                evidence_reference(root, args.scrape_interval_ref, "scrape interval reference")
                if args.scrape_interval_ref is not None else None
            ),
        },
    }
    output = coordinator / "outbox" / "run-contract.yaml"
    created = not output.exists()
    validation = promote_immutable(output, yaml_bytes(artifact), root)
    if created:
        update_state(
            coordinator / "state.yaml",
            status="IN_PROGRESS",
            completed="outbox/run-contract.yaml",
            pending=[],
            next_action="dispatch-metric-inventories",
        )
    validate_workspace(coordinator)
    return f"{validation} path={output.relative_to(root)}"


def read_yaml(path: Path) -> dict[str, Any]:
    result = subprocess.run(
        ["yq", "eval", "-o=json", ".", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    require(result.returncode == 0, result.stderr.strip() or f"cannot read {path}")
    value = json.loads(result.stdout)
    require(isinstance(value, dict), f"{path} must contain an object")
    return value


def create_failure_report(args: argparse.Namespace) -> str:
    run_path = Path(args.run_contract).resolve()
    run = read_yaml(run_path)
    root = Path(run.get("repository_root", "")).resolve()
    validate_artifact(root, run_path)
    workspace = Path(run["workspace"])
    coordinator = workspace / "coordinator" / run["run_id"]
    require(coordinator.is_dir(), "coordinator workspace is not initialized")

    artifact = {
        "schema_version": 1,
        "artifact_type": "failure-report",
        "run_id": run["run_id"],
        "revision": args.revision,
        "inputs": {"run-contract": sha256(run_path)},
        "status": args.status,
        "failed_stage": args.failed_stage,
        "owner": args.owner,
        "code": args.code,
        "summary": args.summary,
        "evidence_refs": args.evidence,
    }
    output = coordinator / "outbox" / "failure-report.yaml"
    validation = promote_immutable(
        output,
        yaml_bytes(artifact),
        root,
        [f"run-contract={run_path}"],
    )
    update_state(
        coordinator / "state.yaml",
        status=args.status,
        completed="outbox/failure-report.yaml",
        pending=[],
        next_action="complete",
    )
    validate_workspace(coordinator)
    return f"{validation} path={output.relative_to(root)}"


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    subparsers = result.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run-contract", help="create and validate a coordinator run contract")
    run.add_argument("--repository-root", required=True)
    run.add_argument("--project-name", required=True)
    run.add_argument("--run-id", required=True)
    run.add_argument("--final-source", required=True)
    run.add_argument("--schema", choices=["V2", "CLASSIC"], default="V2")
    run.add_argument("--grafana-version")
    run.add_argument("--grafonnet-revision")
    run.add_argument("--render-program", default="jsonnet")
    run.add_argument("--render-arg", action="append")
    run.add_argument("--timeout-seconds", type=int, default=120)
    run.add_argument("--datasource-access", action="store_true")
    run.add_argument("--dashboard-api-validation", action="store_true")
    run.add_argument("--publish-requested", action="store_true")
    run.add_argument("--application-namespace-label", default="kubernetes_namespace")
    run.add_argument("--application-pod-label", default="kubernetes_pod_name")
    run.add_argument("--kubernetes-namespace-label", default="namespace")
    run.add_argument("--kubernetes-pod-label", default="pod")
    run.add_argument("--cluster-label")
    run.add_argument("--fixed-selector-ref", action="append", default=[])
    run.add_argument("--population-ref", action="append", default=[])
    run.add_argument("--scrape-interval-ref")

    failure = subparsers.add_parser("failure-report", help="create and validate a terminal failure report")
    failure.add_argument("--run-contract", required=True)
    failure.add_argument("--status", choices=["FAIL", "BLOCKED"], required=True)
    failure.add_argument("--failed-stage", required=True)
    failure.add_argument("--owner", required=True)
    failure.add_argument("--code", required=True)
    failure.add_argument("--summary", required=True)
    failure.add_argument("--evidence", action="append", required=True)
    failure.add_argument("--revision", type=int, default=1)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "run-contract":
            print(create_run_contract(args))
        else:
            print(create_failure_report(args))
    except (CreationError, KeyError, json.JSONDecodeError, OSError) as error:
        print(f"FAIL {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
