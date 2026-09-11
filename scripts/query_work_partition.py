#!/usr/bin/env python3
"""Partition planned PromQL work into typed templates and bounded exceptions."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import coordinator_stage as stage


LABEL = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class PartitionError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise PartitionError(message)


def partition(plan: dict[str, Any], contract: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Route routine panel and required-variable work to closed templates."""
    approved = contract.get("approved")
    questions = plan.get("questions")
    consumers = plan.get("required_consumers")
    require(isinstance(approved, list) and isinstance(questions, list) and isinstance(consumers, list),
            "approved metrics, plan questions, or required consumers are unavailable")
    metrics = {item.get("id"): item for item in approved if isinstance(item, dict) and isinstance(item.get("id"), str)}
    result: dict[str, list[dict[str, Any]]] = {"standard": [], "custom": [], "preserved": []}
    for question in questions:
        require(isinstance(question, dict), "plan question must be an object")
        question_id = question.get("id")
        metric_ids = question.get("metric_ids")
        change = question.get("change")
        require(isinstance(question_id, str) and isinstance(metric_ids, list) and isinstance(change, str),
                "plan question is incomplete")
        if change == "PRESERVED":
            result["preserved"].append({"question_id": question_id, "metric_ids": metric_ids})
            continue
        if len(metric_ids) != 1:
            result["custom"].append({"question_id": question_id, "metric_ids": metric_ids, "reason_code": "MULTI_METRIC"})
            continue
        metric = metrics.get(metric_ids[0])
        require(isinstance(metric, dict), f"question {question_id} references unavailable metric")
        calculation = question.get("calculation")
        retained_labels = question.get("retained_labels")
        if calculation != "rate":
            reason = "UNSUPPORTED_CALCULATION"
        elif metric.get("type") != "counter":
            reason = "COUNTER_TYPE_REQUIRED"
        elif question.get("result_shape") != "TIME_SERIES":
            reason = "TIME_SERIES_REQUIRED"
        elif not isinstance(retained_labels, list) or not retained_labels or len(retained_labels) > 8 or any(
            not isinstance(label, str) or LABEL.fullmatch(label) is None for label in retained_labels
        ):
            reason = "SUPPORTED_GROUPING_REQUIRED"
        else:
            result["standard"].append({
                "question_id": question_id,
                "metric_id": metric_ids[0],
                "template": "counter_rate_by_pod",
                "metric": metric.get("family"),
                "metric_type": "counter",
                "group_by": retained_labels,
                "required_inputs": ["selector", "window"],
            })
            continue
        result["custom"].append({"question_id": question_id, "metric_ids": metric_ids, "reason_code": reason})

    for consumer in consumers:
        require(isinstance(consumer, dict), "required consumer must be an object")
        consumer_id = consumer.get("id")
        role = consumer.get("role")
        rendered_name = consumer.get("rendered_name")
        metric_ids = consumer.get("metric_ids")
        require(isinstance(consumer_id, str) and isinstance(role, str) and isinstance(rendered_name, str)
                and isinstance(metric_ids, list), "required consumer is incomplete")
        if role == "VARIABLE" and rendered_name in {"namespace", "pod"} and len(metric_ids) == 1:
            metric = metrics.get(metric_ids[0])
            require(isinstance(metric, dict), f"required consumer {consumer_id} references unavailable metric")
            result["standard"].append({
                "consumer_id": consumer_id,
                "role": role,
                "rendered_name": rendered_name,
                "metric_id": metric_ids[0],
                "template": f"{rendered_name}_variable",
                "metric": metric.get("family"),
                "required_inputs": ["label"],
                "optional_inputs": ["selector"],
                "required_record_fields": ["editor_ref_id"],
            })
            continue
        reason = "ANNOTATION_SEMANTICS_REQUIRED" if role == "ANNOTATION" else "VARIABLE_TEMPLATE_UNAVAILABLE"
        result["custom"].append({
            "consumer_id": consumer_id,
            "role": role,
            "rendered_name": rendered_name,
            "metric_ids": metric_ids,
            "reason_code": reason,
        })
    return result


def emit(plan_path: Path, contract_path: Path, output: Path) -> dict[str, Any]:
    work = partition(stage.read_yaml(plan_path), stage.read_yaml(contract_path))
    payload = {
        "schema_version": 1,
        "kind": "query-work-partition",
        "dashboard_plan_sha256": stage.sha256(plan_path),
        "metrics_contract_sha256": stage.sha256(contract_path),
        **work,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    require(len(encoded.encode()) <= 64 * 1024, "query work partition exceeds 64 KiB")
    if output.exists() or output.is_symlink():
        require(output.is_file() and not output.is_symlink(), "query work partition is not a regular file")
        try:
            existing = json.loads(output.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise PartitionError("query work partition is invalid") from error
        require(existing == payload, "query work partition does not match current inputs")
        return payload
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(encoded, encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticket", type=Path, default=Path("inbox/job.yaml"), help="ticket; defaults to inbox/job.yaml")
    parser.add_argument("--output", type=Path, default=Path("evidence/query-work-partition.json"))
    args = parser.parse_args()
    try:
        ticket, _, _, _, inputs, _ = stage.validate_ticket(args.ticket)
        require(ticket["agent"] == "promql-builder", "ticket is not for promql-builder")
        payload = emit(inputs["dashboard-plan"], inputs["metrics-contract"], args.output)
    except (OSError, PartitionError, stage.StageError, KeyError, TypeError) as error:
        print(f"FAIL query-work-partition: {error}", file=sys.stderr)
        return 1
    print(f"PASS query-work-partition standard={len(payload['standard'])} custom={len(payload['custom'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
