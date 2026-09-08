#!/usr/bin/env python3
"""Validate closed, digest-bound dashboard workflow artifacts."""

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


MAX_BYTES = {
    "run-contract": 16 * 1024,
    "application-metrics": 64 * 1024,
    "kubernetes-metrics": 64 * 1024,
    "metrics-contract": 64 * 1024,
    "dashboard-plan": 64 * 1024,
    "query-pack": 128 * 1024,
    "query-review": 32 * 1024,
    "dashboard-build": 32 * 1024,
    "dashboard-review": 32 * 1024,
    "publish-report": 16 * 1024,
    "failure-report": 16 * 1024,
}
HARD_LIMITS = {
    "approved_metrics": 40,
    "changed_questions": 12,
    "changed_panels": 12,
    "changed_queries": 24,
    "total_panels": 48,
    "total_queries": 64,
    "findings": 20,
}
COMMON = {"schema_version", "artifact_type", "run_id", "revision", "inputs", "status"}
TYPE_FIELDS = {
    "run-contract": {
        "repository_root", "workspace", "source", "rendered_candidate_path", "render",
        "schema", "limits", "capabilities", "selector_proposals",
    },
    "application-metrics": {"catalog_ref", "metrics", "omission_counts"},
    "kubernetes-metrics": {"catalog_ref", "metrics", "omission_counts"},
    "metrics-contract": {"approved", "rejected", "not_considered", "selector_contract", "unresolved"},
    "dashboard-plan": {"panel_groups", "questions", "panels", "required_consumers", "omissions", "budgets"},
    "query-pack": {"queries", "live_validation"},
    "query-review": {"query_pack_sha256", "query_count", "live_validation", "findings"},
    "dashboard-build": {
        "candidate_path", "candidate_sha256", "rendered_path", "rendered_sha256",
        "query_pack_sha256", "query_review_sha256", "baseline_state",
        "baseline_sha256", "integrated_query_ids", "checks", "findings",
    },
    "dashboard-review": {
        "build_manifest_sha256", "candidate_sha256", "rendered_sha256",
        "query_pack_sha256", "query_review_sha256", "query_parity",
        "target_dry_run", "findings",
    },
    "publish-report": {
        "dashboard_review_sha256", "promoted_source_sha256", "rendered_sha256",
        "operation", "write_status", "readback_status", "evidence_refs",
    },
    "failure-report": {"failed_stage", "owner", "code", "summary", "evidence_refs"},
}
STATUSES = {
    "run-contract": {"PASS"},
    "application-metrics": {"DONE"},
    "kubernetes-metrics": {"DONE"},
    "metrics-contract": {"PASS"},
    "dashboard-plan": {"PASS"},
    "query-pack": {"PASS"},
    "query-review": {"PASS", "FAIL"},
    "dashboard-build": {"PASS"},
    "dashboard-review": {"PASS", "FAIL"},
    "publish-report": {"PASS"},
    "failure-report": {"FAIL", "BLOCKED"},
}
ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,63}$")
RUN_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
COUNTER_FUNCTION_RE = re.compile(r"\b(?:rate|irate|increase|resets)\s*\(")


class ArtifactError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ArtifactError(message)


def counter_function_arguments(expression: str, where: str) -> list[str]:
    """Return the balanced argument text of counter-only PromQL functions."""
    arguments: list[str] = []
    for match in COUNTER_FUNCTION_RE.finditer(expression):
        start = match.end()
        depth = 1
        quoted = False
        escaped = False
        index = start
        while index < len(expression) and depth:
            char = expression[index]
            if quoted:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    quoted = False
            elif char == '"':
                quoted = True
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            index += 1
        require(depth == 0, f"{where} has an unbalanced counter-only function")
        arguments.append(expression[start:index - 1])
    return arguments


def expression_mentions_metric(expression: str, family: str) -> bool:
    boundary = r"[A-Za-z0-9_:]"
    return re.search(rf"(?<!{boundary}){re.escape(family)}(?!{boundary})", expression) is not None


def strict_object(value: Any, fields: set[str], where: str) -> dict[str, Any]:
    require(isinstance(value, dict), f"{where} must be an object")
    actual = set(value)
    require(actual == fields,
            f"{where} fields mismatch; missing={sorted(fields - actual)} extra={sorted(actual - fields)}")
    return value


def array(value: Any, where: str, maximum: int, minimum: int = 0) -> list[Any]:
    require(isinstance(value, list), f"{where} must be an array")
    require(minimum <= len(value) <= maximum,
            f"{where} must contain {minimum}..{maximum} entries")
    return value


def text(value: Any, where: str, maximum: int = 512, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    require(isinstance(value, str) and value.strip() != "", f"{where} must be a non-empty string")
    require(len(value) <= maximum, f"{where} exceeds {maximum} characters")
    return value


def identifier(value: Any, where: str) -> str:
    result = text(value, where, 64)
    require(ID_RE.fullmatch(result) is not None, f"{where} is not a stable identifier")
    return result


def enum(value: Any, allowed: set[str], where: str) -> str:
    require(value in allowed, f"{where} must be one of {sorted(allowed)}")
    return value


def integer(value: Any, where: str, minimum: int = 0, maximum: int | None = None) -> int:
    require(isinstance(value, int) and not isinstance(value, bool), f"{where} must be an integer")
    require(value >= minimum, f"{where} must be >= {minimum}")
    if maximum is not None:
        require(value <= maximum, f"{where} must be <= {maximum}")
    return value


def digest(value: Any, where: str, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    require(isinstance(value, str) and DIGEST_RE.fullmatch(value) is not None,
            f"{where} must be sha256:<64 lowercase hex characters>")
    return value


def string_array(value: Any, where: str, maximum: int, minimum: int = 0, item_max: int = 256) -> list[str]:
    values = array(value, where, maximum, minimum)
    for index, item in enumerate(values):
        text(item, f"{where}[{index}]", item_max)
    require(len(values) == len(set(values)), f"{where} contains duplicates")
    return values


def sha256_bytes(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def read_artifact(path: Path) -> tuple[bytes, dict[str, Any]]:
    """Read a workflow artifact in the required YAML format through yq v4."""
    require(path.suffix == ".yaml", f"workflow artifact must use a .yaml filename: {path}")
    try:
        raw = path.read_bytes()
        converted = subprocess.run(
            ["yq", "eval", "-o=json", ".", str(path)],
            capture_output=True,
            check=False,
        )
        require(converted.returncode == 0, f"cannot read valid YAML from {path}")
        value = json.loads(converted.stdout)
    except FileNotFoundError as error:
        raise ArtifactError("Mike Farah yq v4 is required to read YAML artifacts") from error
    except (OSError, json.JSONDecodeError) as error:
        raise ArtifactError(f"cannot read valid YAML from {path}: {error}") from error
    require(isinstance(value, dict), f"{path} root must be an object")
    return raw, value


def validate_envelope(data: dict[str, Any], raw_size: int) -> str:
    artifact_type = data.get("artifact_type")
    require(artifact_type in TYPE_FIELDS, f"unsupported artifact_type: {artifact_type!r}")
    strict_object(data, COMMON | TYPE_FIELDS[artifact_type], "$" )
    require(raw_size <= MAX_BYTES[artifact_type],
            f"{artifact_type} exceeds {MAX_BYTES[artifact_type]} bytes")
    require(data["schema_version"] == 1, "schema_version must be 1")
    require(isinstance(data["run_id"], str) and RUN_ID_RE.fullmatch(data["run_id"]) is not None,
            "run_id must be a neutral 1-64 character identifier")
    integer(data["revision"], "revision", 1, 3)
    enum(data["status"], STATUSES[artifact_type], "status")
    require(isinstance(data["inputs"], dict), "inputs must be an object")
    for input_name, input_digest in data["inputs"].items():
        require(input_name in TYPE_FIELDS and input_name != "failure-report",
                f"unknown input artifact type: {input_name}")
        digest(input_digest, f"inputs.{input_name}")
    return artifact_type


def grafonnet_dependencies(repository_root: Path) -> list[tuple[str, Path]]:
    lock_path = repository_root / "jsonnetfile.lock.json"
    if not lock_path.is_file():
        return []
    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ArtifactError(f"cannot read {lock_path}: {error}") from error
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
        dependencies.append((revision, repository_root / "vendor" / normalized / subdir))
    return dependencies


def require_render_executable(program: str, cwd: Path) -> None:
    if "/" in program:
        executable = Path(program)
        if not executable.is_absolute():
            executable = cwd / executable
        require(executable.is_file() and os.access(executable, os.X_OK),
                f"render executable is unavailable: {program}")
    else:
        require(shutil.which(program) is not None, f"render executable is unavailable: {program}")


def validate_run_contract(data: dict[str, Any]) -> None:
    require(data["inputs"] == {}, "run-contract inputs must be empty")
    repository_root = Path(text(data["repository_root"], "repository_root", 2048))
    require(repository_root.is_absolute(), "repository_root must be absolute")
    require(repository_root.is_dir() and not repository_root.is_symlink(),
            "repository_root must identify a regular directory")
    workspace = Path(text(data["workspace"], "workspace", 1024))
    require(workspace.is_absolute(), "workspace must be absolute")
    source = strict_object(data["source"], {
        "final_path", "candidate_path", "baseline_state", "baseline_sha256"
    }, "source")
    final_path = Path(text(source["final_path"], "source.final_path", 2048))
    candidate_path = Path(text(source["candidate_path"], "source.candidate_path", 2048))
    require(final_path.is_absolute() and candidate_path.is_absolute(),
            "source paths must be absolute")
    resolved_root = repository_root.resolve()
    require(resolved_root == Path.cwd().resolve(),
            "repository_root must equal the validator current working directory")
    try:
        final_path.resolve(strict=False).relative_to(resolved_root)
        candidate_path.resolve(strict=False).relative_to(resolved_root)
    except ValueError as error:
        raise ArtifactError("source paths must be inside repository_root") from error
    try:
        workspace_relative = workspace.resolve(strict=False).relative_to(resolved_root)
    except ValueError as error:
        raise ArtifactError("workspace must be inside repository_root") from error
    require(
        len(workspace_relative.parts) == 3
        and workspace_relative.parts[0] == "dashboards"
        and workspace_relative.parts[2] == "workspace",
        "workspace must be dashboards/<project-name>/workspace inside repository_root",
    )
    require(final_path != candidate_path, "candidate and final paths must differ")
    require(final_path.parent == candidate_path.parent, "candidate must be beside final source")
    require(final_path.suffix == ".jsonnet", "final source must be a .jsonnet file")
    require(candidate_path.name == f"{final_path.stem}.candidate.jsonnet",
            "candidate filename must be <final-stem>.candidate.jsonnet")
    state = enum(source["baseline_state"], {"ABSENT", "PRESENT"}, "source.baseline_state")
    baseline = digest(source["baseline_sha256"], "source.baseline_sha256", nullable=True)
    require((state == "ABSENT" and baseline is None) or (state == "PRESENT" and baseline is not None),
            "baseline state and digest disagree")
    rendered_candidate_path = Path(text(
        data["rendered_candidate_path"], "rendered_candidate_path", 2048
    ))
    expected_render_directory = workspace / "dashboard-builder" / data["run_id"] / "evidence"
    require(
        rendered_candidate_path.is_absolute()
        and rendered_candidate_path.parent == expected_render_directory
        and rendered_candidate_path.suffix == ".json",
        "rendered_candidate_path must be a JSON file in the dashboard-builder run evidence directory",
    )

    render = strict_object(data["render"], {"cwd", "argv", "timeout_seconds"}, "render")
    render_cwd = Path(text(render["cwd"], "render.cwd", 2048))
    require(render_cwd.is_absolute() and render_cwd.is_dir() and not render_cwd.is_symlink(),
            "render.cwd must identify an absolute regular directory")
    try:
        render_cwd.resolve().relative_to(resolved_root)
    except ValueError as error:
        raise ArtifactError("render.cwd must be inside repository_root") from error
    argv = array(render["argv"], "render.argv", 32, minimum=2)
    for index, item in enumerate(argv):
        text(item, f"render.argv[{index}]", 1024)
    require(argv.count("{source}") == 1,
            "render.argv must contain exactly one standalone {source} argument")
    require(sum(len(item) for item in argv) <= 4096, "render.argv exceeds 4096 characters")
    integer(render["timeout_seconds"], "render.timeout_seconds", 1, 300)
    require_render_executable(argv[0], render_cwd)

    schema = strict_object(data["schema"], {"dashboard", "grafana_version", "grafonnet_revision"}, "schema")
    enum(schema["dashboard"], {"V2", "CLASSIC"}, "schema.dashboard")
    text(schema["grafana_version"], "schema.grafana_version", 128, nullable=True)
    revision = text(schema["grafonnet_revision"], "schema.grafonnet_revision", 256, nullable=True)
    dependencies = grafonnet_dependencies(resolved_root)
    if dependencies:
        require(revision is not None,
                "schema.grafonnet_revision is required when Grafonnet is locked locally")
        matches = [path for locked_revision, path in dependencies if locked_revision == revision]
        require(matches, "schema.grafonnet_revision is absent from jsonnetfile.lock.json")
        require(any(path.is_dir() for path in matches),
                "schema.grafonnet_revision is not vendored locally")

    limits = strict_object(data["limits"], set(HARD_LIMITS), "limits")
    for name, hard_maximum in HARD_LIMITS.items():
        integer(limits[name], f"limits.{name}", 1, hard_maximum)
    require(limits["changed_panels"] <= limits["total_panels"], "changed_panels exceeds total_panels")
    require(limits["changed_queries"] <= limits["total_queries"], "changed_queries exceeds total_queries")

    capabilities = strict_object(data["capabilities"], {
        "datasource_access", "dashboard_api_validation", "dashboard_v2_openapi",
        "publish_requested"
    }, "capabilities")
    for name in {"datasource_access", "dashboard_api_validation", "publish_requested"}:
        value = capabilities[name]
        require(isinstance(value, bool), f"capabilities.{name} must be boolean")
    openapi_status = enum(capabilities["dashboard_v2_openapi"], {
        "SUPPORTED", "NOT_CONFIGURED", "UNAUTHORIZED", "NOT_ADVERTISED",
        "UNREACHABLE", "NOT_APPLICABLE",
    }, "capabilities.dashboard_v2_openapi")
    if schema["dashboard"] == "V2":
        require(openapi_status != "NOT_APPLICABLE",
                "V2 dashboard requires a Dashboard V2 OpenAPI capability result")
        if capabilities["dashboard_api_validation"]:
            require(openapi_status == "SUPPORTED",
                    "configured dashboard API validation requires supported Dashboard V2 OpenAPI")
    else:
        require(openapi_status == "NOT_APPLICABLE",
                "non-V2 dashboard requires dashboard_v2_openapi NOT_APPLICABLE")
    require(isinstance(data["selector_proposals"], dict), "selector_proposals must be an object")


def validate_metric_record(record: Any, where: str, artifact_type: str) -> None:
    fields = {
        "id", "source", "category", "family", "members", "type", "unit", "help",
        "observed_labels", "stored_labels", "match_keys", "population", "lifecycle",
        "availability", "cardinality_risk", "evidence_refs", "limitations",
    }
    item = strict_object(record, fields, where)
    identifier(item["id"], f"{where}.id")
    source = enum(item["source"], {
        "APPLICATION", "PROCESS", "KSM", "KUBELET", "SCRAPE", "SCHEDULER", "RECORDING_RULE"
    }, f"{where}.source")
    category = enum(item["category"], {"BUSINESS", "PROCESS", "KUBERNETES"}, f"{where}.category")
    if artifact_type == "application-metrics":
        require(category in {"BUSINESS", "PROCESS"}, f"{where} has invalid application category")
        require(source in {"APPLICATION", "PROCESS", "RECORDING_RULE"}, f"{where} has invalid application source")
    else:
        require(category == "KUBERNETES", f"{where} must use KUBERNETES category")
        require(source in {"KSM", "KUBELET", "SCRAPE", "SCHEDULER", "RECORDING_RULE"},
                f"{where} has invalid Kubernetes source")
    text(item["family"], f"{where}.family", 256)
    string_array(item["members"], f"{where}.members", 16, item_max=256)
    enum(item["type"], {"counter", "gauge", "histogram", "summary", "info", "stateset", "unknown"},
         f"{where}.type")
    text(item["unit"], f"{where}.unit", 64, nullable=True)
    text(item["help"], f"{where}.help", 512, nullable=True)
    string_array(item["observed_labels"], f"{where}.observed_labels", 32, item_max=128)
    string_array(item["stored_labels"], f"{where}.stored_labels", 32, item_max=128)
    string_array(item["match_keys"], f"{where}.match_keys", 16, item_max=128)
    text(item["population"], f"{where}.population", 256)
    text(item["lifecycle"], f"{where}.lifecycle", 256)
    enum(item["availability"], {"OBSERVED", "LIVE_VERIFIED", "DOCUMENTED", "UNVERIFIED"},
         f"{where}.availability")
    enum(item["cardinality_risk"], {"LOW", "MEDIUM", "HIGH", "UNKNOWN"}, f"{where}.cardinality_risk")
    string_array(item["evidence_refs"], f"{where}.evidence_refs", 4, item_max=512)
    string_array(item["limitations"], f"{where}.limitations", 6, item_max=256)


def validate_metric_shortlist(data: dict[str, Any], artifact_type: str) -> None:
    text(data["catalog_ref"], "catalog_ref", 1024, nullable=True)
    records = array(data["metrics"], "metrics", 48)
    ids: set[str] = set()
    for index, record in enumerate(records):
        validate_metric_record(record, f"metrics[{index}]", artifact_type)
        metric_id = record["id"]
        require(metric_id not in ids, f"duplicate metric id: {metric_id}")
        ids.add(metric_id)
    require(isinstance(data["omission_counts"], dict), "omission_counts must be an object")
    for name, count in data["omission_counts"].items():
        identifier(name, f"omission_counts key {name!r}")
        integer(count, f"omission_counts.{name}", 0)


def validate_selector_contract(value: Any) -> None:
    item = strict_object(value, {
        "application_namespace_label", "application_pod_label", "kubernetes_namespace_label",
        "kubernetes_pod_label", "cluster_label", "fixed_selector_refs", "population_notes",
        "scrape_interval_ref",
    }, "selector_contract")
    for name in {
        "application_namespace_label", "application_pod_label", "kubernetes_namespace_label",
        "kubernetes_pod_label", "cluster_label"
    }:
        text(item[name], f"selector_contract.{name}", 128, nullable=True)
    string_array(item["fixed_selector_refs"], "selector_contract.fixed_selector_refs", 8, item_max=512)
    string_array(item["population_notes"], "selector_contract.population_notes", 8, item_max=256)
    text(item["scrape_interval_ref"], "selector_contract.scrape_interval_ref", 512, nullable=True)


def metric_sources(inputs: dict[str, dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for artifact_type in {"application-metrics", "kubernetes-metrics"}:
        artifact = inputs.get(artifact_type)
        if artifact is None:
            continue
        for metric in artifact["metrics"]:
            key = (artifact_type, metric["id"])
            require(key not in result, f"duplicate source metric: {key}")
            result[key] = metric
    return result


def validate_metrics_contract(data: dict[str, Any], inputs: dict[str, dict[str, Any]], limits: dict[str, int]) -> None:
    sources = metric_sources(inputs)
    approved = array(data["approved"], "approved", limits["approved_metrics"], minimum=1)
    approved_fields = {
        "id", "source_artifact", "source_metric_id", "source", "category", "family", "type", "unit",
        "semantics", "lifecycle", "label_layer", "identity_labels", "bounded_dimensions",
        "availability", "allowed_use", "risks", "evidence_refs",
    }
    approved_ids: set[str] = set()
    covered: set[tuple[str, str]] = set()
    approved_labels_by_layer: dict[str, set[str]] = {
        "APPLICATION_STORED": set(),
        "KUBERNETES_NATIVE": set(),
    }
    for index, record in enumerate(approved):
        where = f"approved[{index}]"
        item = strict_object(record, approved_fields, where)
        approved_id = identifier(item["id"], f"{where}.id")
        require(approved_id not in approved_ids, f"duplicate approved metric id: {approved_id}")
        approved_ids.add(approved_id)
        source_artifact = enum(item["source_artifact"], {"application-metrics", "kubernetes-metrics"},
                               f"{where}.source_artifact")
        source_metric_id = identifier(item["source_metric_id"], f"{where}.source_metric_id")
        key = (source_artifact, source_metric_id)
        require(key in sources, f"{where} references absent source metric {key}")
        require(key not in covered, f"source metric reviewed more than once: {key}")
        covered.add(key)
        original = sources[key]
        for field in {"source", "category", "family", "type"}:
            require(item[field] == original[field], f"{where}.{field} disagrees with source metric")
        text(item["unit"], f"{where}.unit", 64, nullable=True)
        text(item["semantics"], f"{where}.semantics", 512)
        text(item["lifecycle"], f"{where}.lifecycle", 256)
        label_layer = enum(item["label_layer"], {"APPLICATION_STORED", "KUBERNETES_NATIVE"},
                           f"{where}.label_layer")
        expected_layer = "KUBERNETES_NATIVE" if item["category"] == "KUBERNETES" else "APPLICATION_STORED"
        require(label_layer == expected_layer,
                f"{where}.label_layer must be {expected_layer} for {item['category']} metrics")
        discovered_labels = set(original["observed_labels"]) | set(original["stored_labels"]) | set(original["match_keys"])
        identity_labels = set(string_array(
            item["identity_labels"], f"{where}.identity_labels", 16, item_max=128
        ))
        bounded_dimensions = set(string_array(
            item["bounded_dimensions"], f"{where}.bounded_dimensions", 16, item_max=128
        ))
        require(identity_labels | bounded_dimensions <= discovered_labels,
                f"{where} introduces labels absent from its source evidence")
        approved_labels_by_layer[label_layer].update(discovered_labels)
        enum(item["availability"], {"VERIFIED", "UNVERIFIED"}, f"{where}.availability")
        allowed_use = enum(item["allowed_use"], {"PLAN", "PRESERVE_ONLY"}, f"{where}.allowed_use")
        if allowed_use == "PLAN":
            require(item["availability"] == "VERIFIED", f"{where} PLAN metric must be VERIFIED")
        string_array(item["risks"], f"{where}.risks", 8, item_max=128)
        string_array(item["evidence_refs"], f"{where}.evidence_refs", 6, item_max=512)

    disposition_fields = {"source_artifact", "metric_id", "reason_code", "reason"}
    rejected = array(data["rejected"], "rejected", 48 * max(1, len(inputs) - 1))
    for index, record in enumerate(rejected):
        where = f"rejected[{index}]"
        item = strict_object(record, disposition_fields, where)
        key = (enum(item["source_artifact"], {"application-metrics", "kubernetes-metrics"},
                    f"{where}.source_artifact"), identifier(item["metric_id"], f"{where}.metric_id"))
        require(key in sources and key not in covered, f"invalid or repeated rejected metric: {key}")
        covered.add(key)
        identifier(item["reason_code"], f"{where}.reason_code")
        text(item["reason"], f"{where}.reason", 256)

    not_considered_fields = {"source_artifact", "metric_id"}
    remaining = array(data["not_considered"], "not_considered", 48 * max(1, len(inputs) - 1))
    for index, record in enumerate(remaining):
        where = f"not_considered[{index}]"
        item = strict_object(record, not_considered_fields, where)
        key = (enum(item["source_artifact"], {"application-metrics", "kubernetes-metrics"},
                    f"{where}.source_artifact"), identifier(item["metric_id"], f"{where}.metric_id"))
        require(key in sources and key not in covered, f"invalid or repeated not-considered metric: {key}")
        covered.add(key)
    require(covered == set(sources), "every shortlisted metric must be approved, rejected, or not_considered")
    validate_selector_contract(data["selector_contract"])
    selectors = data["selector_contract"]
    for name in {"application_namespace_label", "application_pod_label"}:
        label = selectors[name]
        if label is not None:
            require(label in approved_labels_by_layer["APPLICATION_STORED"],
                    f"selector_contract.{name} is absent from approved application evidence")
    for name in {"kubernetes_namespace_label", "kubernetes_pod_label"}:
        label = selectors[name]
        if label is not None:
            require(label in approved_labels_by_layer["KUBERNETES_NATIVE"],
                    f"selector_contract.{name} is absent from approved Kubernetes evidence")
    cluster_label = selectors["cluster_label"]
    if cluster_label is not None:
        require(cluster_label in set().union(*approved_labels_by_layer.values()),
                "selector_contract.cluster_label is absent from approved evidence")
    string_array(data["unresolved"], "unresolved", 12, item_max=256)


def approved_metric_map(inputs: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in inputs["metrics-contract"]["approved"]}


def validate_plan(data: dict[str, Any], inputs: dict[str, dict[str, Any]], limits: dict[str, int]) -> None:
    metrics = approved_metric_map(inputs)
    new_dashboard = inputs["run-contract"]["source"]["baseline_state"] == "ABSENT"
    groups = array(data["panel_groups"], "panel_groups", 12, minimum=1)
    group_ids: set[str] = set()
    group_fields = {"id", "title", "placement", "order"}
    for index, record in enumerate(groups):
        where = f"panel_groups[{index}]"
        item = strict_object(record, group_fields, where)
        group_id = identifier(item["id"], f"{where}.id")
        require(group_id not in group_ids, f"duplicate group id: {group_id}")
        group_ids.add(group_id)
        text(item["title"], f"{where}.title", 128)
        enum(item["placement"], {"OVERVIEW", "APPLICATION", "KUBERNETES", "PROCESS", "DETAIL"},
             f"{where}.placement")
        integer(item["order"], f"{where}.order", 0, 99)

    questions = array(data["questions"], "questions", limits["total_panels"], minimum=1)
    question_ids: set[str] = set()
    question_metrics: dict[str, set[str]] = {}
    question_fields = {
        "id", "text", "priority", "category", "metric_ids", "calculation", "result_shape",
        "retained_labels", "no_data_requirement", "change",
    }
    changed_questions = 0
    for index, record in enumerate(questions):
        where = f"questions[{index}]"
        item = strict_object(record, question_fields, where)
        question_id = identifier(item["id"], f"{where}.id")
        require(question_id not in question_ids, f"duplicate question id: {question_id}")
        question_ids.add(question_id)
        text(item["text"], f"{where}.text", 256)
        enum(item["priority"], {"MUST", "SHOULD"}, f"{where}.priority")
        enum(item["category"], {"BUSINESS", "PROCESS", "KUBERNETES"}, f"{where}.category")
        metric_ids = set(string_array(item["metric_ids"], f"{where}.metric_ids", 6, minimum=1, item_max=64))
        require(metric_ids <= set(metrics), f"{where} references unapproved metrics")
        change = enum(item["change"], {"NEW", "MODIFIED", "PRESERVED"}, f"{where}.change")
        if new_dashboard:
            require(change == "NEW", f"{where}.change must be NEW without a baseline dashboard")
        if change != "PRESERVED":
            changed_questions += 1
            require(all(metrics[metric_id]["allowed_use"] == "PLAN" for metric_id in metric_ids),
                    f"{where} uses PRESERVE_ONLY metric for changed question")
        text(item["calculation"], f"{where}.calculation", 128)
        enum(item["result_shape"], {"SCALAR", "TIME_SERIES", "LABEL_SET", "DISTRIBUTION"},
             f"{where}.result_shape")
        string_array(item["retained_labels"], f"{where}.retained_labels", 12, item_max=128)
        text(item["no_data_requirement"], f"{where}.no_data_requirement", 256)
        question_metrics[question_id] = metric_ids
    require(changed_questions <= limits["changed_questions"], "changed question limit exceeded")

    panels = array(data["panels"], "panels", limits["total_panels"], minimum=1)
    panel_ids: set[str] = set()
    panel_questions: dict[str, set[str]] = {}
    assigned_questions: set[str] = set()
    panel_fields = {"id", "question_ids", "group_id", "visualization", "placement", "size", "change"}
    changed_panels = 0
    for index, record in enumerate(panels):
        where = f"panels[{index}]"
        item = strict_object(record, panel_fields, where)
        panel_id = identifier(item["id"], f"{where}.id")
        require(panel_id not in panel_ids, f"duplicate panel id: {panel_id}")
        panel_ids.add(panel_id)
        question_refs = set(string_array(item["question_ids"], f"{where}.question_ids", 4, minimum=1, item_max=64))
        require(question_refs <= question_ids, f"{where} references absent questions")
        assigned_questions.update(question_refs)
        group_id = identifier(item["group_id"], f"{where}.group_id")
        require(group_id in group_ids, f"{where} references absent group")
        text(item["visualization"], f"{where}.visualization", 128)
        enum(item["placement"], {"OVERVIEW", "APPLICATION", "KUBERNETES", "PROCESS", "DETAIL"},
             f"{where}.placement")
        enum(item["size"], {"SMALL", "MEDIUM", "WIDE"}, f"{where}.size")
        panel_change = enum(item["change"], {"NEW", "MODIFIED", "PRESERVED"}, f"{where}.change")
        if new_dashboard:
            require(panel_change == "NEW", f"{where}.change must be NEW without a baseline dashboard")
        if panel_change != "PRESERVED":
            changed_panels += 1
        panel_questions[panel_id] = question_refs
    require(changed_panels <= limits["changed_panels"], "changed panel limit exceeded")
    require(assigned_questions == question_ids, "every planned question must be assigned to a panel")

    consumers = array(data["required_consumers"], "required_consumers", 16, minimum=2)
    consumer_ids: set[tuple[str, str]] = set()
    rendered_consumers: set[tuple[str, str]] = set()
    consumer_fields = {"id", "role", "rendered_name", "purpose", "metric_ids"}
    for index, record in enumerate(consumers):
        where = f"required_consumers[{index}]"
        item = strict_object(record, consumer_fields, where)
        consumer_id = identifier(item["id"], f"{where}.id")
        role = enum(item["role"], {"VARIABLE", "ANNOTATION"}, f"{where}.role")
        require((role, consumer_id) not in consumer_ids, f"duplicate required consumer: {(role, consumer_id)}")
        consumer_ids.add((role, consumer_id))
        rendered_name = text(item["rendered_name"], f"{where}.rendered_name", 256)
        require((role, rendered_name) not in rendered_consumers,
                f"duplicate rendered consumer: {(role, rendered_name)}")
        rendered_consumers.add((role, rendered_name))
        text(item["purpose"], f"{where}.purpose", 256)
        metric_ids = set(string_array(item["metric_ids"], f"{where}.metric_ids", 6, minimum=1, item_max=64))
        require(metric_ids <= set(metrics), f"{where} references unapproved metrics")
    require({("VARIABLE", "namespace"), ("VARIABLE", "pod")} <= rendered_consumers,
            "required consumers must include namespace and pod variables")

    omission_fields = {"id", "reason"}
    for index, record in enumerate(array(data["omissions"], "omissions", 24)):
        item = strict_object(record, omission_fields, f"omissions[{index}]")
        identifier(item["id"], f"omissions[{index}].id")
        text(item["reason"], f"omissions[{index}].reason", 256)
    require(data["budgets"] == limits, "budgets must exactly copy run-contract limits")


def validate_query_pack(data: dict[str, Any], inputs: dict[str, dict[str, Any]], run: dict[str, Any]) -> None:
    limits = run["limits"]
    metrics = approved_metric_map(inputs)
    plan = inputs["dashboard-plan"]
    questions = {item["id"]: item for item in plan["questions"]}
    panels = {item["id"]: item for item in plan["panels"]}
    consumers = {(item["role"], item["id"]): item for item in plan["required_consumers"]}
    queries = array(data["queries"], "queries", limits["total_queries"], minimum=1)
    fields = {
        "id", "role", "consumer_id", "consumer_locator", "plugin_query_model", "question_id", "metric_ids", "language",
        "expression", "mode", "datasource_ref", "unit", "result_identity", "no_data_semantics",
        "expected_cardinality", "assumptions", "edge_cases", "change", "validation",
    }
    ids: set[str] = set()
    locators: set[tuple[str, str, str | None]] = set()
    covered_panels: set[str] = set()
    covered_questions: set[str] = set()
    covered_consumers: set[tuple[str, str]] = set()
    changed_queries = 0
    for index, record in enumerate(queries):
        where = f"queries[{index}]"
        item = strict_object(record, fields, where)
        query_id = identifier(item["id"], f"{where}.id")
        require(query_id not in ids, f"duplicate query id: {query_id}")
        ids.add(query_id)
        role = enum(item["role"], {"PANEL", "VARIABLE", "ANNOTATION"}, f"{where}.role")
        consumer_id = identifier(item["consumer_id"], f"{where}.consumer_id")
        locator_value = strict_object(item["consumer_locator"], {"kind", "name", "ref_id"},
                                      f"{where}.consumer_locator")
        locator_kind = enum(locator_value["kind"], {"PANEL", "VARIABLE", "ANNOTATION"},
                            f"{where}.consumer_locator.kind")
        require(locator_kind == role, f"{where} role and locator kind disagree")
        locator_name = text(locator_value["name"], f"{where}.consumer_locator.name", 256)
        ref_id = text(locator_value["ref_id"], f"{where}.consumer_locator.ref_id", 64, nullable=True)
        locator = (role, locator_name, ref_id)
        require(locator not in locators, f"duplicate query consumer locator: {locator}")
        locators.add(locator)
        question_id = item["question_id"]
        metric_ids = set(string_array(item["metric_ids"], f"{where}.metric_ids", 6, minimum=1, item_max=64))
        require(metric_ids <= set(metrics), f"{where} references unapproved metrics")
        change = enum(item["change"], {"NEW", "MODIFIED", "PRESERVED"}, f"{where}.change")
        if run["source"]["baseline_state"] == "ABSENT":
            require(change == "NEW", f"{where}.change must be NEW without a baseline dashboard")
        if change != "PRESERVED":
            changed_queries += 1
            require(all(metrics[metric_id]["allowed_use"] == "PLAN" for metric_id in metric_ids),
                    f"{where} uses PRESERVE_ONLY metric in changed query")

        if role == "PANEL":
            require(item["plugin_query_model"] is None,
                    f"{where}.plugin_query_model must be null for panel queries")
            require(consumer_id in panels, f"{where} references absent panel")
            require(locator_name == consumer_id, f"{where} panel locator name must equal panel id")
            require(ref_id is not None, f"{where} panel query requires ref_id")
            question_id = identifier(question_id, f"{where}.question_id")
            require(question_id in set(panels[consumer_id]["question_ids"]),
                    f"{where} question is not assigned to its panel")
            require(metric_ids <= set(questions[question_id]["metric_ids"]),
                    f"{where} uses metric outside planned question")
            covered_panels.add(consumer_id)
            covered_questions.add(question_id)
            enum(item["language"], {"PROMQL"}, f"{where}.language")
            enum(item["mode"], {"INSTANT", "RANGE"}, f"{where}.mode")
        else:
            require(question_id is None, f"{where} non-panel question_id must be null")
            consumer_key = (role, consumer_id)
            require(consumer_key in consumers, f"{where} references absent required consumer")
            require(locator_name == consumers[consumer_key]["rendered_name"],
                    f"{where} locator name disagrees with planned rendered_name")
            require(metric_ids <= set(consumers[consumer_key]["metric_ids"]),
                    f"{where} uses metric outside planned consumer")
            covered_consumers.add(consumer_key)
            if role == "VARIABLE":
                plugin_model = strict_object(
                    item["plugin_query_model"], {"qry_type", "editor_ref_id"},
                    f"{where}.plugin_query_model",
                )
                qry_type = plugin_model["qry_type"]
                if run["schema"]["dashboard"] == "V2":
                    integer(qry_type, f"{where}.plugin_query_model.qry_type", 0, 64)
                else:
                    require(qry_type is None or (
                        isinstance(qry_type, int) and not isinstance(qry_type, bool) and 0 <= qry_type <= 64
                    ), f"{where}.plugin_query_model.qry_type must be null or an integer")
                editor_ref = text(
                    plugin_model["editor_ref_id"],
                    f"{where}.plugin_query_model.editor_ref_id", 128,
                )
                require(ref_id == editor_ref,
                        f"{where} locator ref_id must equal plugin_query_model.editor_ref_id")
                enum(item["language"], {"PROMETHEUS_VARIABLE"}, f"{where}.language")
                enum(item["mode"], {"VARIABLE"}, f"{where}.mode")
            else:
                require(item["plugin_query_model"] is None,
                        f"{where}.plugin_query_model must be null for annotations")
                enum(item["language"], {"PROMQL"}, f"{where}.language")
                enum(item["mode"], {"RANGE"}, f"{where}.mode")

        expression = text(item["expression"], f"{where}.expression", 4096)
        counter_arguments = counter_function_arguments(expression, f"{where}.expression")
        if counter_arguments:
            counter_compatible = {"counter", "histogram", "summary"}
            compatible_ids = {
                metric_id for metric_id in metric_ids
                if metrics[metric_id]["type"] in counter_compatible
            }
            require(
                compatible_ids,
                f"{where} uses a counter-only function but no referenced metric has a counter-compatible type",
            )
            for metric_id in metric_ids - compatible_ids:
                family = metrics[metric_id]["family"]
                require(
                    not any(expression_mentions_metric(argument, family) for argument in counter_arguments),
                    f"{where} applies a counter-only function to {metric_id} declared as {metrics[metric_id]['type']}",
                )
        text(item["datasource_ref"], f"{where}.datasource_ref", 256)
        require(item["datasource_ref"] == "${datasource}",
                f"{where}.datasource_ref must be ${{datasource}}")
        text(item["unit"], f"{where}.unit", 64, nullable=True)
        string_array(item["result_identity"], f"{where}.result_identity", 16, item_max=128)
        text(item["no_data_semantics"], f"{where}.no_data_semantics", 256)
        text(item["expected_cardinality"], f"{where}.expected_cardinality", 256)
        string_array(item["assumptions"], f"{where}.assumptions", 4, item_max=256)
        string_array(item["edge_cases"], f"{where}.edge_cases", 6, item_max=256)
        validation = strict_object(item["validation"], {"static", "live", "evidence_refs"}, f"{where}.validation")
        enum(validation["static"], {"PASS"}, f"{where}.validation.static")
        live_status = enum(validation["live"], {"PASS", "UNVERIFIED"}, f"{where}.validation.live")
        expected_live = "PASS" if run["capabilities"]["datasource_access"] else "UNVERIFIED"
        require(live_status == expected_live, f"{where}.validation.live disagrees with run capability")
        string_array(validation["evidence_refs"], f"{where}.validation.evidence_refs", 4, item_max=512)
    require(changed_queries <= limits["changed_queries"], "changed query limit exceeded")
    require(covered_panels == set(panels), "every planned panel must have a query")
    require(covered_questions == set(questions), "every planned question must have a query")
    require(covered_consumers == set(consumers), "every required variable/annotation consumer must have a query")
    live_validation = enum(data["live_validation"], {"PASS", "UNVERIFIED"}, "live_validation")
    expected_live = "PASS" if run["capabilities"]["datasource_access"] else "UNVERIFIED"
    require(live_validation == expected_live, "query-pack live_validation disagrees with run capability")


def validate_query_finding(value: Any, where: str, query_ids: set[str]) -> None:
    item = strict_object(value, {"query_id", "code", "evidence_ref", "required_change"}, where)
    query_id = identifier(item["query_id"], f"{where}.query_id")
    require(query_id in query_ids, f"{where} references absent query")
    identifier(item["code"], f"{where}.code")
    text(item["evidence_ref"], f"{where}.evidence_ref", 512, nullable=True)
    text(item["required_change"], f"{where}.required_change", 512)


def validate_query_review(data: dict[str, Any], inputs: dict[str, dict[str, Any]], run: dict[str, Any]) -> None:
    limits = run["limits"]
    pack = inputs["query-pack"]
    require(data["query_pack_sha256"] == data["inputs"]["query-pack"], "query_pack_sha256 mismatch")
    require(data["query_count"] == len(pack["queries"]), "query_count mismatch")
    integer(data["query_count"], "query_count", 1, limits["total_queries"])
    live = enum(data["live_validation"], {"PASS", "UNVERIFIED", "FAIL"}, "live_validation")
    findings = array(data["findings"], "findings", limits["findings"])
    query_ids = {item["id"] for item in pack["queries"]}
    for index, finding in enumerate(findings):
        validate_query_finding(finding, f"findings[{index}]", query_ids)
    if data["status"] == "PASS":
        require(not findings, "PASS query review must have zero findings")
        require(live != "FAIL", "PASS query review cannot have failed live validation")
        expected_live = "PASS" if run["capabilities"]["datasource_access"] else "UNVERIFIED"
        require(live == expected_live, "query-review live_validation disagrees with run capability")
    else:
        require(bool(findings), "FAIL query review requires findings")


def validate_build_finding(value: Any, where: str) -> None:
    item = strict_object(value, {"owner", "code", "summary", "evidence_ref"}, where)
    enum(item["owner"], {"DASHBOARD_BUILD", "QUERY_PACK_CHANGE_REQUIRED", "METRICS_OR_PLAN_CHANGE_REQUIRED"},
         f"{where}.owner")
    identifier(item["code"], f"{where}.code")
    text(item["summary"], f"{where}.summary", 512)
    text(item["evidence_ref"], f"{where}.evidence_ref", 512, nullable=True)


def file_digest(path_value: Any, where: str) -> str:
    path = Path(text(path_value, where, 2048))
    try:
        require(path.is_file() and not path.is_symlink(), f"{where} must identify a regular non-symlink file")
        return sha256_bytes(path.read_bytes())
    except OSError as error:
        raise ArtifactError(f"cannot read {where}: {error}") from error


def validate_dashboard_build(data: dict[str, Any], inputs: dict[str, dict[str, Any]], run: dict[str, Any]) -> None:
    source = run["source"]
    require(data["candidate_path"] == source["candidate_path"], "candidate_path disagrees with run contract")
    require(data["rendered_path"] == run["rendered_candidate_path"], "rendered_path disagrees with run contract")
    candidate_path = Path(data["candidate_path"])
    if candidate_path.exists() or candidate_path.is_symlink():
        source_digest = file_digest(str(candidate_path), "candidate_path")
    else:
        source_digest = file_digest(source["final_path"], "promoted final source")
    require(data["candidate_sha256"] == source_digest,
            "candidate_sha256 does not match candidate or promoted final source")
    require(data["rendered_sha256"] == file_digest(data["rendered_path"], "rendered_path"),
            "rendered_sha256 does not match rendered file")
    require(data["query_pack_sha256"] == data["inputs"]["query-pack"], "query_pack_sha256 mismatch")
    require(data["query_review_sha256"] == data["inputs"]["query-review"], "query_review_sha256 mismatch")
    require(data["baseline_state"] == source["baseline_state"], "baseline_state mismatch")
    require(data["baseline_sha256"] == source["baseline_sha256"], "baseline_sha256 mismatch")
    query_ids = {item["id"] for item in inputs["query-pack"]["queries"]}
    integrated = set(string_array(data["integrated_query_ids"], "integrated_query_ids",
                                  run["limits"]["total_queries"], minimum=1, item_max=64))
    require(integrated == query_ids, "integrated_query_ids must exactly match query-pack ids")
    checks = strict_object(data["checks"], {
        "format", "render", "json", "query_parity", "local_schema",
        "layout_references", "variable_payloads",
    }, "checks")
    for name in {"format", "render", "json", "query_parity", "layout_references", "variable_payloads"}:
        enum(checks[name], {"PASS"}, f"checks.{name}")
    enum(checks["local_schema"], {"PASS", "UNVERIFIED"}, "checks.local_schema")
    findings = array(data["findings"], "findings", run["limits"]["findings"])
    for index, finding in enumerate(findings):
        validate_build_finding(finding, f"findings[{index}]")
    require(not findings, "PASS dashboard build must have zero findings")


def validate_dashboard_review(data: dict[str, Any], inputs: dict[str, dict[str, Any]], run: dict[str, Any]) -> None:
    build = inputs["dashboard-build"]
    require(data["build_manifest_sha256"] == data["inputs"]["dashboard-build"],
            "build_manifest_sha256 mismatch")
    require(data["candidate_sha256"] == build["candidate_sha256"], "candidate_sha256 mismatch")
    require(data["rendered_sha256"] == build["rendered_sha256"], "rendered_sha256 mismatch")
    require(data["query_pack_sha256"] == data["inputs"]["query-pack"], "query_pack_sha256 mismatch")
    require(data["query_review_sha256"] == data["inputs"]["query-review"], "query_review_sha256 mismatch")
    parity = enum(data["query_parity"], {"PASS", "FAIL"}, "query_parity")
    dry_run = enum(data["target_dry_run"], {"PASS", "NOT_CONFIGURED", "FAIL"}, "target_dry_run")
    if run["capabilities"]["dashboard_api_validation"]:
        require(dry_run == "PASS" or data["status"] == "FAIL",
                "configured dashboard API validation requires target_dry_run PASS")
    else:
        require(dry_run == "NOT_CONFIGURED" or data["status"] == "FAIL",
                "target_dry_run must be NOT_CONFIGURED when validation is unavailable")
    findings = array(data["findings"], "findings", run["limits"]["findings"])
    finding_fields = {"owner", "code", "artifact_ref", "evidence_ref", "required_change"}
    for index, finding in enumerate(findings):
        where = f"findings[{index}]"
        item = strict_object(finding, finding_fields, where)
        enum(item["owner"], {"DASHBOARD_BUILD", "QUERY_PACK_CHANGE_REQUIRED", "METRICS_OR_PLAN_CHANGE_REQUIRED"},
             f"{where}.owner")
        identifier(item["code"], f"{where}.code")
        text(item["artifact_ref"], f"{where}.artifact_ref", 512)
        text(item["evidence_ref"], f"{where}.evidence_ref", 512, nullable=True)
        text(item["required_change"], f"{where}.required_change", 512)
    if data["status"] == "PASS":
        require(not findings, "PASS dashboard review must have zero findings")
        require(parity == "PASS", "PASS dashboard review requires query parity PASS")
        require(dry_run != "FAIL", "PASS dashboard review cannot have failed dry-run")
    else:
        require(bool(findings), "FAIL dashboard review requires findings")


def validate_failure_report(data: dict[str, Any]) -> None:
    identifier(data["failed_stage"], "failed_stage")
    owner = data["owner"]
    require(owner == "USER" or (isinstance(owner, str) and ID_RE.fullmatch(owner) is not None),
            "owner must be USER or an agent id")
    identifier(data["code"], "code")
    text(data["summary"], "summary", 512)
    string_array(data["evidence_refs"], "evidence_refs", 3, item_max=512)


def evidence_reference_values(value: Any) -> list[str]:
    references: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "evidence_ref" and isinstance(item, str):
                references.append(item)
            elif key == "evidence_refs" and isinstance(item, list):
                references.extend(reference for reference in item if isinstance(reference, str))
            else:
                references.extend(evidence_reference_values(item))
    elif isinstance(value, list):
        for item in value:
            references.extend(evidence_reference_values(item))
    return references


def evidence_path(reference: str, artifact_path: Path) -> Path:
    raw_path = reference.split("#", 1)[0]
    line_match = re.fullmatch(r"(.+):([1-9][0-9]*)", raw_path)
    if line_match is not None:
        raw_path = line_match.group(1)
    path = Path(raw_path)
    if not path.is_absolute():
        base = artifact_path.parent.parent if artifact_path.parent.name == "outbox" else artifact_path.parent
        path = base / path
    return path.resolve(strict=False)


def validate_evidence_references(data: dict[str, Any], artifact_path: Path, run: dict[str, Any]) -> None:
    repository_root = Path(run["repository_root"]).resolve()
    for reference in evidence_reference_values(data):
        path = evidence_path(reference, artifact_path)
        try:
            path.relative_to(repository_root)
        except ValueError as error:
            raise ArtifactError(f"evidence reference escapes repository root: {reference}") from error
        require(path.is_file() and not path.is_symlink(),
                f"evidence reference does not identify a regular file: {reference}")


def validate_publish_report(
    data: dict[str, Any], inputs: dict[str, dict[str, Any]], run: dict[str, Any]
) -> None:
    require(run["capabilities"]["publish_requested"],
            "publish-report is invalid when publication was not requested")
    review = inputs["dashboard-review"]
    build = inputs["dashboard-build"]
    require(data["dashboard_review_sha256"] == data["inputs"]["dashboard-review"],
            "dashboard_review_sha256 mismatch")
    require(data["promoted_source_sha256"] == review["candidate_sha256"],
            "promoted source was not the reviewed candidate")
    require(data["promoted_source_sha256"] == file_digest(
        run["source"]["final_path"], "promoted final source"
    ), "promoted_source_sha256 does not match final source")
    require(data["rendered_sha256"] == review["rendered_sha256"] == build["rendered_sha256"],
            "rendered_sha256 mismatch")
    require(data["rendered_sha256"] == file_digest(build["rendered_path"], "reviewed rendered dashboard"),
            "rendered_sha256 does not match rendered file")
    enum(data["operation"], {"CREATE", "UPDATE"}, "operation")
    enum(data["write_status"], {"PASS"}, "write_status")
    enum(data["readback_status"], {"PASS"}, "readback_status")
    string_array(data["evidence_refs"], "evidence_refs", 4, item_max=512)


def expected_input_names(artifact_type: str, declared: set[str]) -> None:
    exact = {
        "run-contract": set(),
        "application-metrics": {"run-contract"},
        "kubernetes-metrics": {"run-contract"},
        "dashboard-plan": {"run-contract", "metrics-contract"},
        "query-pack": {"run-contract", "metrics-contract", "dashboard-plan"},
        "query-review": {"run-contract", "metrics-contract", "dashboard-plan", "query-pack"},
        "dashboard-build": {"run-contract", "metrics-contract", "dashboard-plan", "query-pack", "query-review"},
        "dashboard-review": {"run-contract", "dashboard-plan", "query-pack", "query-review", "dashboard-build"},
        "publish-report": {"run-contract", "dashboard-build", "dashboard-review"},
    }
    if artifact_type == "metrics-contract":
        allowed = {"run-contract", "application-metrics", "kubernetes-metrics"}
        require(declared <= allowed and "run-contract" in declared,
                "metrics-contract has invalid input set")
        require(bool(declared & {"application-metrics", "kubernetes-metrics"}),
                "metrics-contract requires at least one metric shortlist")
    elif artifact_type == "failure-report":
        require("run-contract" in declared, "failure-report requires run-contract input")
    else:
        require(declared == exact[artifact_type],
                f"{artifact_type} inputs must be exactly {sorted(exact[artifact_type])}")


def parse_bindings(bindings: list[str], option: str) -> dict[str, Path]:
    supplied_paths: dict[str, Path] = {}
    for binding in bindings:
        require("=" in binding, f"invalid {option} {binding!r}; expected type=path")
        name, raw_path = binding.split("=", 1)
        require(name not in supplied_paths, f"duplicate {option} {name}")
        supplied_paths[name] = Path(raw_path)
    return supplied_paths


def load_and_bind_inputs(
    data: dict[str, Any], bindings: list[str], support_bindings: list[str] | None = None
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    supplied_paths = parse_bindings(bindings, "--input")
    support_paths = parse_bindings(support_bindings or [], "--support")
    require(not (set(supplied_paths) & set(support_paths)),
            "an artifact type cannot be both --input and --support")
    declared = set(data["inputs"])
    require(set(supplied_paths) == declared,
            f"supplied input names differ; declared={sorted(declared)} supplied={sorted(supplied_paths)}")
    expected_input_names(data["artifact_type"], declared)

    artifacts: dict[str, dict[str, Any]] = {}
    actual_digests: dict[str, str] = {}
    raw_sizes: dict[str, int] = {}
    artifact_paths: dict[str, Path] = {}
    for name, path in (supplied_paths | support_paths).items():
        raw, artifact = read_artifact(path)
        require(artifact.get("artifact_type") == name,
                f"input {name} points to artifact_type {artifact.get('artifact_type')!r}")
        validate_envelope(artifact, len(raw))
        require(artifact["run_id"] == data["run_id"], f"input {name} has another run_id")
        expected_success = "DONE" if name in {"application-metrics", "kubernetes-metrics"} else "PASS"
        require(artifact["status"] == expected_success, f"input {name} is not {expected_success}")
        actual = sha256_bytes(raw)
        if name in supplied_paths:
            require(data["inputs"][name] == actual, f"input digest mismatch for {name}")
        artifacts[name] = artifact
        actual_digests[name] = actual
        raw_sizes[name] = len(raw)
        artifact_paths[name] = path

    required_support: set[str] = set()
    visited: set[str] = set()
    visiting: set[str] = set()

    def validate_input(name: str) -> None:
        if name in visited:
            return
        require(name not in visiting, "artifact input graph contains a cycle")
        visiting.add(name)
        current = artifacts[name]
        nested: dict[str, dict[str, Any]] = {}
        for dependency, expected_digest in current["inputs"].items():
            require(dependency in artifacts,
                    f"missing --support {dependency}=PATH required by input {name}")
            if dependency not in supplied_paths:
                required_support.add(dependency)
            require(actual_digests[dependency] == expected_digest,
                    f"nested input digest mismatch: {name} -> {dependency}")
            validate_input(dependency)
            nested[dependency] = artifacts[dependency]
        validate_artifact(current, raw_sizes[name], nested, artifact_paths[name])
        visiting.remove(name)
        visited.add(name)

    for name in supplied_paths:
        validate_input(name)
    require(set(support_paths) == required_support,
            f"support names differ; required={sorted(required_support)} supplied={sorted(support_paths)}")
    return artifacts, actual_digests


def validate_artifact(
    data: dict[str, Any],
    raw_size: int,
    inputs: dict[str, dict[str, Any]],
    artifact_path: Path,
) -> None:
    artifact_type = validate_envelope(data, raw_size)
    run = data if artifact_type == "run-contract" else inputs.get("run-contract")
    if artifact_type != "run-contract":
        require(run is not None, f"{artifact_type} requires run-contract input")
        validate_run_contract(run)
    if artifact_type == "run-contract":
        validate_run_contract(data)
    elif artifact_type in {"application-metrics", "kubernetes-metrics"}:
        validate_metric_shortlist(data, artifact_type)
    elif artifact_type == "metrics-contract":
        validate_metrics_contract(data, inputs, run["limits"])
    elif artifact_type == "dashboard-plan":
        validate_plan(data, inputs, run["limits"])
    elif artifact_type == "query-pack":
        validate_query_pack(data, inputs, run)
    elif artifact_type == "query-review":
        validate_query_review(data, inputs, run)
    elif artifact_type == "dashboard-build":
        validate_dashboard_build(data, inputs, run)
    elif artifact_type == "dashboard-review":
        validate_dashboard_review(data, inputs, run)
    elif artifact_type == "publish-report":
        validate_publish_report(data, inputs, run)
    else:
        validate_failure_report(data)
    if artifact_type != "run-contract":
        validate_evidence_references(data, artifact_path, run)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--input", action="append", default=[], metavar="TYPE=PATH")
    parser.add_argument("--support", action="append", default=[], metavar="TYPE=PATH")
    args = parser.parse_args()
    try:
        raw, data = read_artifact(args.artifact)
        validate_envelope(data, len(raw))
        inputs, _ = load_and_bind_inputs(data, args.input, args.support)
        validate_artifact(data, len(raw), inputs, args.artifact)
    except (ArtifactError, KeyError, TypeError) as error:
        print(f"FAIL {error}", file=sys.stderr)
        return 1
    print(f"PASS {data['artifact_type']} {sha256_bytes(raw)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
