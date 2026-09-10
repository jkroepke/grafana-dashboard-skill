#!/usr/bin/env python3
"""Emit or checkpoint fixed Kubernetes and Istio metric-inventory candidates."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import coordinator_stage as stage
import metric_queue


CATALOG = Path(__file__).resolve().parents[1] / "knowledge" / "kubernetes" / "presets.md"


def metric(
    identifier: str,
    source: str,
    family: str,
    metric_type: str,
    unit: str | None,
    labels: list[str],
    population: str,
    limitation: str,
) -> dict[str, object]:
    return {
        "id": identifier,
        "source": source,
        "category": "KUBERNETES",
        "family": family,
        "members": [family],
        "type": metric_type,
        "unit": unit,
        "help": None,
        "observed_labels": [],
        "stored_labels": [],
        "documented_labels": labels,
        "match_keys": [],
        "population": population,
        "lifecycle": "unknown",
        "availability": "DOCUMENTED",
        "cardinality_risk": "MEDIUM",
        "evidence_refs": [f"{CATALOG}#{identifier.lower()}"],
        "limitations": [limitation],
    }


KUBERNETES_WORKLOAD = [
    metric("K001", "KUBELET", "container_cpu_usage_seconds_total", "counter", "seconds", ["namespace", "pod", "container"], "regular containers", "Exclude cAdvisor pseudo-containers after target verification."),
    metric("K002", "KUBELET", "container_memory_working_set_bytes", "gauge", "bytes", ["namespace", "pod", "container"], "regular containers", "Working set is not OOM headroom."),
    metric("K003", "KUBELET", "container_cpu_cfs_throttled_seconds_total", "counter", "seconds", ["namespace", "pod", "container"], "regular containers", "Throttled time is not a fraction of periods."),
    metric("K004", "KSM", "kube_pod_container_resource_requests", "gauge", None, ["namespace", "pod", "container", "resource", "unit"], "container scheduling requests", "Resource and unit dimensions must be verified before comparison."),
    metric("K005", "KSM", "kube_pod_container_resource_limits", "gauge", None, ["namespace", "pod", "container", "resource", "unit"], "container configured limits", "A missing or zero limit is not numeric capacity."),
    metric("K006", "KSM", "kube_pod_status_ready", "gauge", None, ["namespace", "pod", "condition"], "pods", "Condition value and availability require target verification."),
    metric("K007", "KSM", "kube_pod_container_status_restarts_total", "counter", None, ["namespace", "pod", "container"], "containers", "Restart coverage and reset behavior require target verification."),
    metric("K008", "KUBELET", "container_oom_events_total", "counter", None, ["namespace", "pod", "container"], "containers", "This metric is collector-dependent."),
    metric("K009", "KSM", "kube_pod_status_phase", "gauge", None, ["namespace", "pod", "phase"], "pods", "Use the verified one-hot state semantics only."),
    metric("K010", "KSM", "kube_pod_status_scheduled", "gauge", None, ["namespace", "pod", "condition"], "pods", "Condition value and availability require target verification."),
    metric("K011", "KSM", "kube_pod_container_state_started", "gauge", "seconds", ["namespace", "pod", "container"], "containers", "A timestamp gauge is not an annotation event without event-time handling."),
    metric("K012", "KSM", "kube_pod_container_status_waiting_reason", "gauge", None, ["namespace", "pod", "container", "reason"], "containers", "Reason-label cardinality must remain bounded."),
    metric("K013", "KSM", "kube_pod_status_reason", "gauge", None, ["namespace", "pod", "reason"], "pods", "Reason-label cardinality must remain bounded."),
]

ISTIO_WORKLOAD = [
    metric("I001", "ISTIO", "istio_requests_total", "counter", None, ["reporter", "source_workload_namespace", "destination_workload_namespace", "response_code", "request_protocol"], "HTTP, HTTP/2, and gRPC traffic", "Telemetry overrides can remove or alter this metric and its labels."),
    metric("I002", "ISTIO", "istio_request_duration_milliseconds", "histogram", "milliseconds", ["reporter", "source_workload_namespace", "destination_workload_namespace", "request_protocol"], "HTTP, HTTP/2, and gRPC traffic", "Prometheus histogram members and labels require target verification."),
    metric("I003", "ISTIO", "istio_request_bytes", "histogram", "bytes", ["reporter", "source_workload_namespace", "destination_workload_namespace", "request_protocol"], "HTTP, HTTP/2, and gRPC traffic", "Prometheus histogram members and labels require target verification."),
    metric("I004", "ISTIO", "istio_response_bytes", "histogram", "bytes", ["reporter", "source_workload_namespace", "destination_workload_namespace", "request_protocol"], "HTTP, HTTP/2, and gRPC traffic", "Prometheus histogram members and labels require target verification."),
    metric("I005", "ISTIO", "istio_request_messages_total", "counter", None, ["reporter", "source_workload_namespace", "destination_workload_namespace", "request_protocol"], "gRPC traffic", "Telemetry overrides can remove or alter this metric and its labels."),
    metric("I006", "ISTIO", "istio_response_messages_total", "counter", None, ["reporter", "source_workload_namespace", "destination_workload_namespace", "request_protocol"], "gRPC traffic", "Telemetry overrides can remove or alter this metric and its labels."),
    metric("I007", "ISTIO", "istio_tcp_sent_bytes_total", "counter", "bytes", ["reporter", "source_workload_namespace", "destination_workload_namespace"], "TCP traffic", "Telemetry overrides can remove or alter this metric and its labels."),
    metric("I008", "ISTIO", "istio_tcp_received_bytes_total", "counter", "bytes", ["reporter", "source_workload_namespace", "destination_workload_namespace"], "TCP traffic", "Telemetry overrides can remove or alter this metric and its labels."),
    metric("I009", "ISTIO", "istio_tcp_connections_opened_total", "counter", None, ["reporter", "source_workload_namespace", "destination_workload_namespace"], "TCP traffic", "Telemetry overrides can remove or alter this metric and its labels."),
    metric("I010", "ISTIO", "istio_tcp_connections_closed_total", "counter", None, ["reporter", "source_workload_namespace", "destination_workload_namespace"], "TCP traffic", "Telemetry overrides can remove or alter this metric and its labels."),
]

PRESETS = {"kubernetes-workload": KUBERNETES_WORKLOAD, "istio-workload": ISTIO_WORKLOAD}


def selected(names: list[str]) -> list[dict[str, object]]:
    requested = set(names)
    if "all" in requested:
        requested = set(PRESETS)
    return [record for name in PRESETS for record in PRESETS[name] if name in requested]


def write_yaml(path: Path, value: object) -> None:
    rendered = subprocess.run(
        ["yq", "eval", "-p=json", "-o=yaml", "."],
        input=json.dumps(value, sort_keys=True), capture_output=True, text=True, check=False,
    )
    if rendered.returncode:
        raise ValueError("Mike Farah yq v4 is required to write preset records")
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False) as draft:
        draft.write(rendered.stdout)
        draft_path = Path(draft.name)
    os.replace(draft_path, path)


def checkpoint(workspace: Path, records: list[dict[str, object]]) -> dict[str, object]:
    workspace = workspace.resolve()
    records_dir = workspace / "records" / "metrics"
    pending_dir = workspace / "records" / "pending"
    done_dir = workspace / "records" / "done"
    if not (workspace / "state.yaml").is_file() or not done_dir.is_dir():
        raise ValueError("workspace must be initialized for the kubernetes-metrics agent")
    records_dir.mkdir(parents=True, exist_ok=True)
    pending_dir.mkdir(parents=True, exist_ok=True)

    previous_cwd = Path.cwd()
    try:
        os.chdir(workspace)
        metric_queue.reconcile()
        for index, record in enumerate(records, 1):
            name = f"{index:04d}-{record['id']}.yaml"
            checkpoint_path = records_dir / name
            pending_path = pending_dir / name
            done_path = done_dir / name
            if done_path.exists():
                if not checkpoint_path.is_file():
                    raise ValueError(f"completed preset is missing its checkpoint: {name}")
                continue
            if not checkpoint_path.exists():
                write_yaml(checkpoint_path, record)
            if not pending_path.exists():
                write_yaml(pending_path, {"id": record["id"], "source": "preset"})
            metric_queue.complete(name, checkpoint_path)
    finally:
        os.chdir(previous_cwd)
    return {
        "catalog_ref": str(CATALOG),
        "checkpoint_count": len(records),
        "workspace": str(workspace),
    }


def complete_stage(ticket_path: Path, records: list[dict[str, object]]) -> str:
    ticket, _, _, _, _, _ = stage.validate_ticket(ticket_path)
    stage.require(ticket["agent"] == "kubernetes-metrics", "ticket is not for kubernetes-metrics")
    agent_root = ticket_path.resolve().parent.parent
    checkpoint(agent_root, records)
    artifact = {
        "schema_version": 1,
        "artifact_type": "kubernetes-metrics",
        "run_id": ticket["run_id"],
        "revision": ticket["revision"],
        "inputs": {name: binding["sha256"] for name, binding in ticket["inputs"].items()},
        "status": "DONE",
        "catalog_ref": str(CATALOG),
        "metrics": records,
        "omission_counts": {},
        "namespace_scope_ref": ticket["namespace_scope"]["evidence_ref"],
        "namespace_scope_sha256": ticket["namespace_scope"]["sha256"],
    }
    draft = agent_root / "tmp" / "kubernetes-metrics.yaml"
    write_yaml(draft, artifact)
    draft_check = subprocess.run(
        [sys.executable, str(Path(__file__).with_name("stage_check.py")), "--ticket", str(ticket_path), "--draft"],
        capture_output=True, text=True, check=False,
    )
    if draft_check.returncode:
        raise ValueError(draft_check.stderr.strip() or "preset artifact draft validation failed")
    final = agent_root / ticket["outputs"]["artifact"]
    os.replace(draft, final)
    terminal = subprocess.run(
        [sys.executable, str(Path(__file__).with_name("stage_check.py")), "--ticket", str(ticket_path)],
        capture_output=True, text=True, check=False,
    )
    if terminal.returncode:
        raise ValueError(terminal.stderr.strip() or "preset artifact terminal validation failed")
    return terminal.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preset", action="append", choices=[*PRESETS, "all"])
    parser.add_argument("--workspace", type=Path,
                        help="initialized kubernetes-metrics agent workspace to populate")
    parser.add_argument("--ticket", type=Path,
                        help="kubernetes-metrics ticket; creates the complete terminal artifact")
    args = parser.parse_args()
    if args.workspace is not None and args.ticket is not None:
        parser.error("--workspace and --ticket are mutually exclusive")
    records = selected(args.preset or ["all"])
    try:
        if args.ticket is not None:
            print(complete_stage(args.ticket, records))
        elif args.workspace is not None:
            print(json.dumps(checkpoint(args.workspace, records), sort_keys=True))
        else:
            print(json.dumps({"catalog_ref": str(CATALOG), "metrics": records}, sort_keys=True))
    except (OSError, ValueError, stage.StageError, metric_queue.QueueError) as error:
        print(f"FAIL kubernetes-presets: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
