#!/usr/bin/env python3
"""Create, validate, dispatch, and accept digest-bound specialist jobs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import create_coordinator_artifact as coordinator_artifact
import validate_workflow_artifact as workflow


SCRIPT_DIR = Path(__file__).resolve().parent
INIT_WORKSPACE = SCRIPT_DIR / "init_agent_workspace.sh"
ARTIFACT_VALIDATOR = SCRIPT_DIR / "validate_workflow_artifact.py"
KUBERNETES_PRESETS = SCRIPT_DIR / "kubernetes_presets.py"

STAGES = {
    "application-metrics": ("application-metrics", "application-metrics.yaml"),
    "kubernetes-metrics": ("kubernetes-metrics", "kubernetes-metrics.yaml"),
    "metrics-reviewer": ("metrics-contract", "metrics-contract.yaml"),
    "dashboard-architect": ("dashboard-plan", "dashboard-plan.yaml"),
    "promql-builder": ("query-pack", "query-pack.yaml"),
    "promql-reviewer": ("query-review", "query-review.yaml"),
    "dashboard-builder": ("dashboard-build", "dashboard-build.yaml"),
    "dashboard-reviewer": ("dashboard-review", "dashboard-review.yaml"),
    "dashboard-publisher": ("publish-report", "publish-report.yaml"),
}
ARTIFACT_OWNERS = {artifact_type: agent for agent, (artifact_type, _) in STAGES.items()}
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
SAFE_LIMIT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,63}$")
RESPONSE_RE = re.compile(
    r"^(DONE|PASS|FAIL|BLOCKED) ([A-Za-z][A-Za-z0-9._-]{0,63}) "
    r"(artifact|report)=([^\s]{1,160}) sha256=(sha256:[0-9a-f]{64})$"
)


class StageError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise StageError(message)


def sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def read_yaml(path: Path) -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["yq", "eval", "-o=json", ".", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as error:
        raise StageError("Mike Farah yq v4 is required") from error
    require(result.returncode == 0, result.stderr.strip() or f"cannot read {path}")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise StageError(f"cannot decode YAML from {path}") from error
    require(isinstance(value, dict), f"{path} must contain an object")
    return value


def read_namespace_scope(path: Path) -> list[str]:
    """Read the canonical bare JSON namespace-scope evidence file."""
    require(path.is_file() and not path.is_symlink(), "namespace scope evidence is unavailable")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise StageError("namespace scope evidence is invalid") from error
    require(isinstance(value, list) and value and all(isinstance(item, str) and item for item in value),
            "namespace scope evidence must be a non-empty string array")
    return sorted(set(value))


def yaml_bytes(value: dict[str, Any]) -> bytes:
    return coordinator_artifact.yaml_bytes(value)


def atomic_yaml(path: Path, value: dict[str, Any]) -> None:
    raw = yaml_bytes(value)
    require(len(raw) <= 8192, f"{path.name} exceeds 8192 bytes")
    require(not path.exists(), f"refusing duplicate write to immutable file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    draft = path.parent / f".{path.name}.{os.getpid()}"
    try:
        draft.write_bytes(raw)
        os.link(draft, path)
    except FileExistsError as error:
        raise StageError(f"refusing duplicate write to immutable file: {path}") from error
    finally:
        if draft.exists():
            draft.unlink()


def run_yq_update(path: Path, expression: str, environment: dict[str, str]) -> None:
    env = os.environ.copy()
    env.update(environment)
    result = subprocess.run(
        ["yq", "eval", "-i", expression, str(path)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    require(result.returncode == 0, result.stderr.strip() or f"cannot update {path}")


def load_run(run_contract: Path) -> tuple[dict[str, Any], Path, Path]:
    run_contract = run_contract.resolve()
    run = read_yaml(run_contract)
    require(run.get("artifact_type") == "run-contract", "--run-contract is not a run-contract")
    root = Path(run.get("repository_root", "")).resolve()
    workspace = Path(run.get("workspace", "")).resolve()
    require(root.is_dir() and workspace.is_dir(), "run-contract repository/workspace is unavailable")
    require(Path.cwd().resolve() == workspace, "run coordinator commands from workspace")
    validate_artifact_file(run_contract, {})
    expected = workspace / "coordinator" / run["run_id"] / "outbox" / "run-contract.yaml"
    require(run_contract == expected, "run-contract is outside its canonical coordinator workspace")
    return run, root, workspace


def path_within(path: Path, root: Path, label: str) -> Path:
    resolved = path.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise StageError(f"{label} escapes repository root") from error
    return resolved


def ticket_path_value(path: Path, workspace: Path) -> str:
    return os.path.relpath(path, workspace)


def resolve_ticket_path(value: str, workspace: Path, root: Path, label: str) -> Path:
    require(isinstance(value, str) and value and len(value) <= 2048, f"{label} must be a path")
    path = Path(value)
    if not path.is_absolute():
        path = workspace / path
    return path_within(path, root, label)


def canonical_artifact(workspace: Path, run_id: str, artifact_type: str, run_path: Path) -> Path:
    if artifact_type == "run-contract":
        return run_path
    owner = ARTIFACT_OWNERS[artifact_type]
    filename = STAGES[owner][1]
    return workspace / owner / run_id / "outbox" / filename


def acceptance_path(workspace: Path, run_id: str, agent: str) -> Path:
    return workspace / "coordinator" / run_id / "records" / "stages" / f"{agent}.yaml"


def active_ticket(workspace: Path, agent: str) -> Path:
    """Find the one active ticket for an explicitly named workflow role."""
    candidates: list[Path] = []
    for state_path in sorted((workspace / "coordinator").glob("*/state.yaml")):
        if state_path.is_symlink():
            continue
        state = read_yaml(state_path)
        if state.get("status") == "IN_PROGRESS" and agent in state.get("pending", []):
            candidates.append(workspace / agent / state_path.parent.name / "inbox" / "job.yaml")
    require(len(candidates) == 1, f"no unique active ticket for {agent}")
    ticket = candidates[0]
    require(ticket.is_file() and not ticket.is_symlink(), "active stage ticket is unavailable")
    return ticket


def require_accepted(workspace: Path, run_id: str, artifact_type: str, artifact_path: Path) -> None:
    if artifact_type == "run-contract":
        return
    agent = ARTIFACT_OWNERS[artifact_type]
    path = acceptance_path(workspace, run_id, agent)
    require(path.is_file() and not path.is_symlink(), f"missing accepted input stage: {agent}")
    record = read_yaml(path)
    require(record.get("agent") == agent, f"invalid acceptance record for {agent}")
    require(record.get("artifact_type") == artifact_type, f"acceptance type mismatch for {agent}")
    require(record.get("artifact_sha256") == sha256(artifact_path), f"accepted artifact changed: {agent}")


def direct_input_types(agent: str) -> set[str]:
    artifact_type = STAGES[agent][0]
    if artifact_type == "application-metrics":
        return {"run-contract"}
    if artifact_type == "kubernetes-metrics":
        return {"run-contract", "application-metrics"}
    if artifact_type == "metrics-contract":
        return {"run-contract", "application-metrics", "kubernetes-metrics"}
    exact = {
        "dashboard-plan": {"run-contract", "metrics-contract"},
        "query-pack": {"run-contract", "metrics-contract", "dashboard-plan"},
        "query-review": {"run-contract", "metrics-contract", "dashboard-plan", "query-pack"},
        "dashboard-build": {
            "run-contract", "metrics-contract", "dashboard-plan", "query-pack", "query-review",
        },
        "dashboard-review": {
            "run-contract", "dashboard-plan", "query-pack", "query-review", "dashboard-build",
        },
        "publish-report": {"run-contract", "dashboard-build", "dashboard-review"},
    }
    return exact[artifact_type]


def ticket_namespace_scope(agent: str, direct_paths: dict[str, Path]) -> dict[str, str] | None:
    if agent != "kubernetes-metrics":
        return None
    scope = read_yaml(direct_paths["application-metrics"])["namespace_scope"]
    return {"evidence_ref": scope["evidence_ref"], "sha256": scope["sha256"]}


def dependency_paths(
    direct_paths: dict[str, Path], workspace: Path, run_id: str, run_path: Path
) -> dict[str, Path]:
    all_paths = dict(direct_paths)
    visited: set[str] = set()
    visiting: set[str] = set()

    def visit(artifact_type: str) -> None:
        if artifact_type in visited:
            return
        require(artifact_type not in visiting, "artifact input graph contains a cycle")
        visiting.add(artifact_type)
        data = read_yaml(all_paths[artifact_type])
        require(data.get("artifact_type") == artifact_type, f"{artifact_type} path has another artifact type")
        for dependency in data.get("inputs", {}):
            if dependency not in all_paths:
                all_paths[dependency] = canonical_artifact(workspace, run_id, dependency, run_path)
            require(all_paths[dependency].is_file(), f"missing transitive input: {dependency}")
            require(sha256(all_paths[dependency]) == data["inputs"][dependency],
                    f"transitive input digest mismatch: {artifact_type} -> {dependency}")
            visit(dependency)
        visiting.remove(artifact_type)
        visited.add(artifact_type)

    for name in list(direct_paths):
        visit(name)
    return all_paths


def transitive_names(name: str, paths: dict[str, Path]) -> set[str]:
    direct = set(read_yaml(paths[name]).get("inputs", {}))
    result: set[str] = set()
    visited: set[str] = set()
    visiting: set[str] = set()

    def visit(dependency: str) -> None:
        if dependency in visited:
            return
        require(dependency not in visiting, "artifact input graph contains a cycle")
        visiting.add(dependency)
        for nested in read_yaml(paths[dependency]).get("inputs", {}):
            if nested not in direct:
                result.add(nested)
            visit(nested)
        visiting.remove(dependency)
        visited.add(dependency)

    for dependency in direct:
        visit(dependency)
    return result


def validate_artifact_file(path: Path, paths: dict[str, Path]) -> None:
    data = read_yaml(path)
    direct = set(data.get("inputs", {}))
    command = [sys.executable, str(ARTIFACT_VALIDATOR), str(path)]
    for name in sorted(direct):
        require(name in paths, f"missing input path for {name}")
        command.extend(["--input", f"{name}={paths[name]}"])
    for name in sorted(transitive_names(data["artifact_type"], {**paths, data["artifact_type"]: path})):
        require(name in paths, f"missing support path for {name}")
        command.extend(["--support", f"{name}={paths[name]}"])
    if data["artifact_type"] == "run-contract":
        root = Path(data["repository_root"])
    else:
        require("run-contract" in paths, "artifact graph is missing run-contract")
        root = Path(read_yaml(paths["run-contract"])["repository_root"])
    result = subprocess.run(command, cwd=root, capture_output=True, text=True, check=False)
    require(result.returncode == 0, result.stderr.strip() or f"artifact validation failed: {path}")


def validate_binding_map(value: Any, name: str, workspace: Path, root: Path) -> dict[str, Path]:
    require(isinstance(value, dict), f"ticket.{name} must be an object")
    paths: dict[str, Path] = {}
    for artifact_type, binding in value.items():
        require(artifact_type in workflow.TYPE_FIELDS and artifact_type != "failure-report",
                f"ticket.{name} contains unknown artifact type: {artifact_type}")
        require(isinstance(binding, dict) and set(binding) == {"path", "sha256"},
                f"ticket.{name}.{artifact_type} must contain path and sha256")
        path = resolve_ticket_path(binding["path"], workspace, root, f"ticket.{name}.{artifact_type}.path")
        require(path.is_file() and not path.is_symlink(), f"ticket input is not a regular file: {artifact_type}")
        require(DIGEST_RE.fullmatch(binding["sha256"] or "") is not None,
                f"ticket.{name}.{artifact_type}.sha256 is invalid")
        require(sha256(path) == binding["sha256"], f"ticket digest mismatch: {artifact_type}")
        paths[artifact_type] = path
    return paths


def validate_ticket(path: Path) -> tuple[dict[str, Any], dict[str, Any], Path, Path, dict[str, Path], dict[str, Path]]:
    path = path.resolve()
    require(path.name == "job.yaml" and path.parent.name == "inbox", "ticket must be inbox/job.yaml")
    require(path.is_file() and not path.is_symlink(), "ticket must be a regular file")
    require(path.stat().st_size <= 8192, "ticket exceeds 8192 bytes")
    agent_root = path.parent.parent
    workspace = agent_root.parent.parent
    agent = agent_root.parent.name
    run_id = agent_root.name
    ticket = read_yaml(path)
    expected_fields = {
        "schema_version", "workspace", "run_id", "agent", "revision", "inputs", "supports",
        "evidence_refs", "namespace_scope", "outputs", "limits", "capability_refs",
    }
    require(set(ticket) == expected_fields, "ticket fields are incomplete or unknown")
    require(ticket["schema_version"] == 1 and ticket["revision"] in {1, 2, 3}, "invalid ticket version")
    require(ticket["agent"] == agent and ticket["run_id"] == run_id, "ticket path identity mismatch")
    require(agent in STAGES, f"unknown ticket agent: {agent}")
    require(ticket["workspace"] == str(workspace.resolve()), "ticket workspace mismatch")

    inputs = validate_binding_map(ticket["inputs"], "inputs", workspace, workspace.parents[2])
    require("run-contract" in inputs, "ticket inputs must include run-contract")
    run = read_yaml(inputs["run-contract"])
    root = Path(run.get("repository_root", "")).resolve()
    require(workspace.resolve() == Path(run.get("workspace", "")).resolve(), "ticket belongs to another workspace")
    require(run.get("run_id") == run_id, "ticket belongs to another run")
    inputs = validate_binding_map(ticket["inputs"], "inputs", workspace, root)
    supports = validate_binding_map(ticket["supports"], "supports", workspace, root)
    require(not (set(inputs) & set(supports)), "ticket input cannot also be support")
    workflow.expected_input_names(STAGES[agent][0], set(inputs))
    all_paths = dependency_paths(inputs, workspace, run_id, inputs["run-contract"])
    require(set(supports) == set(all_paths) - set(inputs), "ticket support set does not match input graph")
    for name, support_path in supports.items():
        require(all_paths[name] == support_path, f"ticket support path mismatch: {name}")
    for name, input_path in {**inputs, **supports}.items():
        require_accepted(workspace, run_id, name, input_path)
    for input_path in inputs.values():
        validate_artifact_file(input_path, all_paths)

    require(isinstance(ticket["evidence_refs"], list), "ticket.evidence_refs must be a list")
    for index, reference in enumerate(ticket["evidence_refs"]):
        evidence = resolve_ticket_path(reference, workspace, root, f"ticket.evidence_refs[{index}]")
        require(evidence.is_file() and not evidence.is_symlink(), f"ticket evidence is unavailable: {reference}")
    if agent == "kubernetes-metrics":
        scope = ticket["namespace_scope"]
        require(isinstance(scope, dict) and set(scope) == {"evidence_ref", "sha256"},
                "Kubernetes ticket namespace_scope must contain evidence_ref and sha256")
        application_scope = read_yaml(inputs["application-metrics"])["namespace_scope"]
        require(scope["evidence_ref"] == application_scope["evidence_ref"],
                "Kubernetes ticket namespace scope reference mismatch")
        require(scope["sha256"] == application_scope["sha256"],
                "Kubernetes ticket namespace scope digest mismatch")
    else:
        require(ticket["namespace_scope"] is None,
                "only kubernetes-metrics may receive namespace_scope")
    require(isinstance(ticket["limits"], dict), "ticket.limits must be an object")
    require(set(ticket["limits"]) == set(run["limits"]), "ticket limits must copy run-contract limit names")
    for key, value in ticket["limits"].items():
        require(SAFE_LIMIT_RE.fullmatch(key) is not None and isinstance(value, int) and 0 < value <= run["limits"][key],
                f"invalid ticket limit: {key}")
    require(isinstance(ticket["capability_refs"], list), "ticket.capability_refs must be a list")
    for reference in ticket["capability_refs"]:
        require(isinstance(reference, str) and 0 < len(reference) <= 256,
                "ticket capability refs must be bounded strings")
    outputs = ticket["outputs"]
    require(isinstance(outputs, dict) and set(outputs) == {"artifact", "failure_report", "candidate", "rendered"},
            "ticket.outputs has an invalid shape")
    for key, value in outputs.items():
        if value is not None:
            output_path = Path(value)
            if not output_path.is_absolute():
                output_path = agent_root / output_path
            path_within(output_path, root, f"ticket.outputs.{key}")
    require(outputs["artifact"] == f"outbox/{STAGES[agent][1]}", "ticket artifact output is not canonical")
    require(outputs["failure_report"] == "outbox/failure-report.yaml", "ticket failure output is not canonical")
    if agent == "dashboard-builder":
        require(outputs["candidate"] == run["source"]["candidate_path"], "ticket candidate output is not canonical")
        require(outputs["rendered"] == run["rendered_candidate_path"], "ticket rendered output is not canonical")
    else:
        require(outputs["candidate"] is None and outputs["rendered"] is None,
                "only dashboard-builder may receive candidate/rendered outputs")
    return ticket, run, root, workspace, inputs, supports


def parse_limits(values: list[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        require("=" in value, f"invalid --limit {value!r}; expected name=value")
        name, raw = value.split("=", 1)
        require(SAFE_LIMIT_RE.fullmatch(name) is not None and name not in result, f"invalid --limit name: {name}")
        try:
            result[name] = int(raw)
        except ValueError as error:
            raise StageError(f"invalid --limit value: {value}") from error
        require(result[name] > 0, f"invalid --limit value: {value}")
    return result


def dispatch(args: argparse.Namespace) -> str:
    run, root, workspace = load_run(Path(args.run_contract))
    agent = args.agent
    run_id = run["run_id"]
    coordinator_root = workspace / "coordinator" / run_id
    coordinator_state = read_yaml(coordinator_root / "state.yaml")
    require(coordinator_state["status"] == "IN_PROGRESS", "coordinator is not active")
    active = set(coordinator_state["pending"])
    require(not active, f"cannot dispatch {agent}; active stages: {sorted(active)}")

    artifact_type = STAGES[agent][0]
    direct_names = direct_input_types(agent)
    workflow.expected_input_names(artifact_type, direct_names)
    direct_paths = {
        name: canonical_artifact(workspace, run_id, name, Path(args.run_contract).resolve())
        for name in direct_names
    }
    for name, path in direct_paths.items():
        require(path.is_file() and not path.is_symlink(), f"missing stage input: {name}")
        require_accepted(workspace, run_id, name, path)
    all_paths = dependency_paths(direct_paths, workspace, run_id, Path(args.run_contract).resolve())
    for name in all_paths:
        if name not in direct_names:
            require_accepted(workspace, run_id, name, all_paths[name])
    for path in direct_paths.values():
        validate_artifact_file(path, all_paths)

    initialized = subprocess.run(
        [str(INIT_WORKSPACE), str(root), workspace.parent.name, run_id, agent],
        capture_output=True,
        text=True,
        check=False,
    )
    require(initialized.returncode == 0, initialized.stderr.strip() or "could not initialize agent workspace")
    agent_root = Path(initialized.stdout.strip())
    ticket_path = agent_root / "inbox" / "job.yaml"
    require(not ticket_path.exists(), f"ticket already exists for {agent}; do not dispatch a second writer")
    require(not any((agent_root / "outbox").glob("*.yaml")), f"{agent} already has terminal output")
    state = read_yaml(agent_root / "state.yaml")
    require(state["status"] == "READY", f"{agent} workspace is not READY")

    evidence_refs: list[str] = []
    for raw in args.evidence:
        path = path_within((root / raw) if not Path(raw).is_absolute() else Path(raw), root, "evidence")
        require(path.is_file() and not path.is_symlink(), f"evidence is not a regular file: {raw}")
        evidence_refs.append(ticket_path_value(path, workspace))
    require(len(evidence_refs) <= 16, "too many evidence references")
    require(len(args.capability_ref) <= 16, "too many capability references")
    limits = dict(run["limits"])
    requested_limits = parse_limits(args.limit)
    require(set(requested_limits) <= set(limits), "--limit contains an unknown run limit")
    for name, value in requested_limits.items():
        require(value <= limits[name], f"--limit {name} exceeds the run contract")
    limits.update(requested_limits)

    outputs = {
        "artifact": f"outbox/{STAGES[agent][1]}",
        "failure_report": "outbox/failure-report.yaml",
        "candidate": run["source"]["candidate_path"] if agent == "dashboard-builder" else None,
        "rendered": run["rendered_candidate_path"] if agent == "dashboard-builder" else None,
    }
    ticket = {
        "schema_version": 1,
        "workspace": str(workspace),
        "run_id": run_id,
        "agent": agent,
        "revision": args.revision,
        "inputs": {
            name: {"path": ticket_path_value(path, workspace), "sha256": sha256(path)}
            for name, path in sorted(direct_paths.items())
        },
        "supports": {
            name: {"path": ticket_path_value(path, workspace), "sha256": sha256(path)}
            for name, path in sorted(all_paths.items()) if name not in direct_paths
        },
        "evidence_refs": evidence_refs,
        "namespace_scope": ticket_namespace_scope(agent, direct_paths),
        "outputs": outputs,
        "limits": limits,
        "capability_refs": args.capability_ref,
    }
    atomic_yaml(ticket_path, ticket)
    validate_ticket(ticket_path)

    run_yq_update(
        agent_root / "state.yaml",
        '.status = "IN_PROGRESS" | .completed = [] | .pending = ["inbox/job.yaml"] | '
        '.next_action = "process-ticket"',
        {},
    )
    pending = sorted(active | {agent})
    run_yq_update(
        coordinator_root / "state.yaml",
        '.pending = (strenv(PENDING_JSON) | from_json) | .next_action = "await-specialists"',
        {"PENDING_JSON": json.dumps(pending)},
    )
    coordinator_artifact.validate_workspace(agent_root)
    coordinator_artifact.validate_workspace(coordinator_root)
    if agent == "kubernetes-metrics":
        generated = subprocess.run(
            [str(KUBERNETES_PRESETS), "--ticket", str(ticket_path)],
            cwd=workspace,
            capture_output=True,
            text=True,
            check=False,
        )
        require(generated.returncode == 0,
                generated.stderr.strip() or "could not generate Kubernetes preset artifact")
        response = generated.stdout.strip().splitlines()[-1]
        return accept(argparse.Namespace(ticket=ticket_path, agent=None, response=response, response_file=None))
    return (
        f"{agent} workspace={workspace} agent_run={agent_root} "
        f"ticket={ticket_path.relative_to(root)}"
    )


def accept(args: argparse.Namespace) -> str:
    requested_agent = getattr(args, "agent", None)
    if args.ticket is not None:
        ticket_path = Path(args.ticket).resolve()
    else:
        require(requested_agent is not None, "accept requires --agent when --ticket is omitted")
        ticket_path = active_ticket(Path.cwd().resolve(), requested_agent)
    ticket, run, root, workspace, inputs, supports = validate_ticket(ticket_path)
    require(Path.cwd().resolve() == workspace, "run coordinator commands from workspace")
    agent = ticket["agent"]
    require(requested_agent is None or requested_agent == agent, "--agent does not match the ticket")
    response = args.response
    if args.response_file is not None:
        response_path = path_within(Path(args.response_file), root, "response file")
        require(response_path.is_file() and not response_path.is_symlink(),
                "response file must be a regular repository file")
        response = response_path.read_text(encoding="utf-8").removesuffix("\n")
    require(response is not None and "\n" not in response and len(response) <= 256,
            "stage response must be one line of at most 256 characters")
    match = RESPONSE_RE.fullmatch(response)
    require(match is not None, "stage response does not match the required grammar")
    status, response_stage, field, raw_artifact, response_digest = match.groups()
    require(response_stage == agent, "stage response names another agent")
    expected_field = "report" if status in {"FAIL", "BLOCKED"} else "artifact"
    require(field == expected_field, f"{status} response must use {expected_field}=")
    expected_status = "DONE" if agent in {"application-metrics", "kubernetes-metrics"} else "PASS"
    if status not in {"FAIL", "BLOCKED"}:
        require(status == expected_status, f"{agent} must return {expected_status}")
    failed_review = (
        status == "FAIL"
        and agent in {"promql-reviewer", "dashboard-reviewer"}
        and raw_artifact == ticket["outputs"]["artifact"]
    )
    expected_output = ticket["outputs"]["failure_report" if field == "report" else "artifact"]
    require(raw_artifact == expected_output or failed_review,
            "stage response references an unassigned output")
    raw_artifact_path = Path(raw_artifact)
    if not raw_artifact_path.is_absolute():
        raw_artifact_path = ticket_path.parent.parent / raw_artifact_path
    artifact_path = path_within(raw_artifact_path, root, "response artifact")
    require(artifact_path.is_file() and not artifact_path.is_symlink(), "stage artifact is unavailable")
    require(sha256(artifact_path) == response_digest, "stage response digest mismatch")
    artifact = read_yaml(artifact_path)
    require(artifact.get("status") == status, "stage response status differs from artifact")

    if field == "artifact" or failed_review:
        command = [sys.executable, str(ARTIFACT_VALIDATOR), str(artifact_path)]
        for name, path in sorted(inputs.items()):
            command.extend(["--input", f"{name}={path}"])
        for name, path in sorted(supports.items()):
            command.extend(["--support", f"{name}={path}"])
    else:
        command = [
            sys.executable, str(ARTIFACT_VALIDATOR), str(artifact_path),
            "--input", f"run-contract={inputs['run-contract']}",
        ]
    validation = subprocess.run(command, cwd=root, capture_output=True, text=True, check=False)
    require(validation.returncode == 0, validation.stderr.strip() or "stage artifact validation failed")
    agent_root = ticket_path.parent.parent
    coordinator_artifact.validate_workspace(agent_root)

    coordinator_root = workspace / "coordinator" / run["run_id"]
    coordinator_state = read_yaml(coordinator_root / "state.yaml")
    require(agent in coordinator_state["pending"], f"{agent} is not an active coordinator stage")
    record_path = acceptance_path(workspace, run["run_id"], agent)
    record = {
        "schema_version": 1,
        "run_id": run["run_id"],
        "agent": agent,
        "status": status,
        "ticket_sha256": sha256(ticket_path),
        "artifact_type": artifact["artifact_type"],
        "artifact_path": ticket_path_value(artifact_path, workspace),
        "artifact_sha256": response_digest,
    }
    atomic_yaml(record_path, record)

    if status in {"FAIL", "BLOCKED"}:
        if failed_review:
            failure_owner = agent
            failure_code = "STAGE_REVIEW_FAILED"
            failure_summary = f"{agent} returned a failed review; inspect the accepted review artifact."
        else:
            require(artifact.get("artifact_type") == "failure-report",
                    "failed stage response must reference a failure-report")
            failure_owner = artifact["owner"]
            failure_code = artifact["code"]
            failure_summary = artifact["summary"]
        result = coordinator_artifact.create_failure_report(argparse.Namespace(
            run_contract=str(inputs["run-contract"]),
            status=status,
            failed_stage=agent,
            owner=failure_owner,
            code=failure_code,
            summary=failure_summary,
            evidence=[str(artifact_path)],
            revision=artifact["revision"],
        ))
        return f"ACCEPTED {agent} {status} {result}"

    pending = sorted(set(coordinator_state["pending"]) - {agent})
    completed_ref = f"records/stages/{agent}.yaml"
    run_yq_update(
        coordinator_root / "state.yaml",
        '.completed = ((.completed // []) + [strenv(COMPLETED_REF)] | unique) | '
        '.pending = (strenv(PENDING_JSON) | from_json) | '
        '.next_action = strenv(NEXT_ACTION)',
        {
            "COMPLETED_REF": completed_ref,
            "PENDING_JSON": json.dumps(pending),
            "NEXT_ACTION": "dispatch-next-stage" if not pending else "await-specialists",
        },
    )
    coordinator_artifact.validate_workspace(coordinator_root)
    return f"ACCEPTED {agent} artifact={record['artifact_path']} sha256={response_digest}"


def reset_stage(args: argparse.Namespace) -> str:
    """Reissue one canceled active stage without changing its workspace."""
    run, root, workspace = load_run(Path(args.run_contract))
    require(Path.cwd().resolve() == workspace, "run coordinator commands from workspace")
    agent = args.agent
    coordinator_root = workspace / "coordinator" / run["run_id"]
    coordinator_state = read_yaml(coordinator_root / "state.yaml")
    require(coordinator_state["status"] == "IN_PROGRESS", "coordinator is not active")
    require(set(coordinator_state["pending"]) == {agent}, "only the canceled active stage may be reset")
    agent_root = workspace / agent / run["run_id"]
    ticket_path = agent_root / "inbox" / "job.yaml"
    require(ticket_path.is_file() and not ticket_path.is_symlink(), "stage ticket is unavailable")
    ticket, _, _, _, _, _ = validate_ticket(ticket_path)
    require(ticket["agent"] == agent, "stage ticket names another agent")
    require(not any((agent_root / "outbox").glob("*.yaml")), "stage already has terminal output")
    require(read_yaml(agent_root / "state.yaml")["status"] == "IN_PROGRESS", "stage is not in progress")
    coordinator_artifact.validate_workspace(agent_root)
    coordinator_artifact.validate_workspace(coordinator_root)
    return (
        f"RESET {agent} workspace={workspace} agent_run={agent_root} "
        f"ticket={ticket_path.relative_to(root)}"
    )


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    subparsers = result.add_subparsers(dest="command", required=True)

    dispatch_parser = subparsers.add_parser("dispatch", help="create one immutable specialist ticket")
    dispatch_parser.add_argument("--run-contract", required=True)
    dispatch_parser.add_argument("--agent", choices=sorted(STAGES), required=True)
    dispatch_parser.add_argument("--revision", type=int, choices=(1, 2, 3), default=1)
    dispatch_parser.add_argument("--evidence", action="append", default=[])
    dispatch_parser.add_argument("--capability-ref", action="append", default=[])
    dispatch_parser.add_argument("--limit", action="append", default=[])

    validate_parser = subparsers.add_parser("validate-ticket", help="validate a ticket and every binding")
    validate_parser.add_argument("--ticket", type=Path, default=Path("inbox/job.yaml"))

    accept_parser = subparsers.add_parser("accept", help="validate and accept one specialist response")
    accept_parser.add_argument("--ticket", type=Path)
    accept_parser.add_argument("--agent", choices=sorted(STAGES), help="active stage when --ticket is omitted")
    response_group = accept_parser.add_mutually_exclusive_group(required=True)
    response_group.add_argument("--response")
    response_group.add_argument("--response-file")

    reset_parser = subparsers.add_parser("reset-stage", help="reissue one canceled active stage")
    reset_parser.add_argument("--run-contract", required=True)
    reset_parser.add_argument("--agent", choices=sorted(STAGES), required=True)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "dispatch":
            print(dispatch(args))
        elif args.command == "validate-ticket":
            _, _, _, workspace, _, _ = validate_ticket(Path(args.ticket))
            print(f"PASS job-ticket workspace={workspace}")
        elif args.command == "reset-stage":
            print(reset_stage(args))
        else:
            print(accept(args))
    except (StageError, workflow.ArtifactError, coordinator_artifact.CreationError, OSError, KeyError) as error:
        print(f"FAIL {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
