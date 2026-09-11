#!/usr/bin/env python3
"""Create concrete, scoped selector values for one PromQL review matrix."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import coordinator_stage as stage
from grafana_access import AccessError, grafana_access_from_environment, http_request, prometheus_request_url


class ContextError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContextError(message)


def label_values(body: bytes) -> list[str]:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as error:
        raise ContextError("selector context response is not JSON") from error
    values = payload.get("data") if isinstance(payload, dict) and payload.get("status") == "success" else None
    require(isinstance(values, list) and all(isinstance(value, str) and value for value in values),
            "selector context response is invalid")
    return values


def quoted(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def selector_context(
    scope: list[str], namespace_label: str, pod_label: str, families: list[str], fetch: Callable[[dict[str, Any]], bytes],
) -> dict[str, Any]:
    """Select one namespace and bounded pod choices from ticketed metric families."""
    require(scope and families, "selector context inputs are empty")
    for namespace in scope:
        pods: set[str] = set()
        for family in families:
            request = {
                "operation": "label_values",
                "params": {
                    "label": pod_label,
                    "match[]": f'{family}{{{namespace_label}="{quoted(namespace)}"}}',
                },
            }
            pods.update(label_values(fetch(request)))
        if pods:
            selected = sorted(pods)
            return {
                "schema_version": 1,
                "kind": "query-review-selector-context",
                "namespace_label": namespace_label,
                "namespace": namespace,
                "pod_label": pod_label,
                "one_pod": selected[0],
                "multiple_pod_regex": "|".join(re.escape(value) for value in selected[:2]),
                "all_pod_regex": ".*",
                "pod_count": len(selected),
            }
    raise ContextError("no scoped pod values were observed for ticketed metric families")


def write_context(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False) as draft:
        draft_path = Path(draft.name)
        draft.write(raw)
    try:
        os.link(draft_path, path)
    except FileExistsError as error:
        raise ContextError("selector context already exists") from error
    finally:
        draft_path.unlink(missing_ok=True)


def run(ticket_path: Path) -> dict[str, Any]:
    ticket, _, _, _, inputs, supports = stage.validate_ticket(ticket_path)
    require(ticket["agent"] == "promql-reviewer", "ticket is not for promql-reviewer")
    run_contract = stage.read_yaml(inputs["run-contract"])
    require(run_contract["capabilities"]["datasource_access"], "datasource access is not enabled")
    output = ticket_path.resolve().parent.parent / "evidence" / "query-review-selector-context.json"
    if output.exists():
        return json.loads(output.read_text(encoding="utf-8"))
    application = stage.read_yaml(supports["application-metrics"])
    scope = stage.read_namespace_scope(Path(application["namespace_scope"]["evidence_ref"]))
    contract = stage.read_yaml(inputs["metrics-contract"])
    selectors = contract["selector_contract"]
    namespace_label, pod_label = selectors["application_namespace_label"], selectors["application_pod_label"]
    require(isinstance(namespace_label, str) and isinstance(pod_label, str), "application selector labels are unavailable")
    pack = stage.read_yaml(inputs["query-pack"])
    metric_ids = {metric_id for query in pack["queries"] for metric_id in query["metric_ids"]}
    families = sorted({metric["family"] for metric in contract["approved"] if metric["id"] in metric_ids})
    access = grafana_access_from_environment()
    value = selector_context(
        scope, namespace_label, pod_label, families,
        lambda request: http_request(access, "GET", prometheus_request_url(access, request)),
    )
    write_context(output, value)
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticket", type=Path, default=Path("inbox/job.yaml"), help="ticket; defaults to inbox/job.yaml")
    args = parser.parse_args()
    try:
        value = run(args.ticket)
    except (OSError, AccessError, ContextError, stage.StageError, KeyError, TypeError) as error:
        print(f"FAIL query-review-context: {error}", file=sys.stderr)
        return 1
    print(f"PASS query-review-context namespace={value['namespace']} pods={value['pod_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
