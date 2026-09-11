#!/usr/bin/env python3
"""Project one reviewed query with its ticket-bound plan and metric capabilities."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import coordinator_stage as stage


class ReviewCapabilitiesError(ValueError):
    pass


METRIC_FIELDS = (
    "id", "family", "type", "unit", "semantics", "lifecycle", "label_layer",
    "identity_labels", "bounded_dimensions", "availability", "allowed_use", "risks",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ReviewCapabilitiesError(message)


def query_ids(pack: dict[str, Any]) -> list[str]:
    """Return the stable IDs of the queries available for individual review."""
    queries = pack.get("queries")
    require(isinstance(queries, list), "query pack queries are unavailable")
    identifiers = [item.get("id") for item in queries if isinstance(item, dict)]
    require(len(identifiers) == len(queries) and all(isinstance(item, str) for item in identifiers),
            "query pack has an invalid query ID")
    return sorted(identifiers)


def projection(pack: dict[str, Any], contract: dict[str, Any], plan: dict[str, Any], query_id: str) -> dict[str, Any]:
    """Return the compact evidence required to review one exact query record."""
    queries = pack.get("queries")
    approved = contract.get("approved")
    questions = plan.get("questions")
    consumers = plan.get("required_consumers")
    require(all(isinstance(value, list) for value in (queries, approved, questions, consumers)),
            "query-review inputs are incomplete")
    query = next((item for item in queries if isinstance(item, dict) and item.get("id") == query_id), None)
    require(isinstance(query, dict), f"query {query_id} is unavailable")
    metric_ids = query.get("metric_ids")
    require(isinstance(metric_ids, list) and all(isinstance(item, str) for item in metric_ids),
            f"query {query_id} has invalid metric IDs")
    metrics = {item.get("id"): item for item in approved if isinstance(item, dict) and isinstance(item.get("id"), str)}
    selected_metrics: list[dict[str, Any]] = []
    for metric_id in metric_ids:
        metric = metrics.get(metric_id)
        require(isinstance(metric, dict) and set(METRIC_FIELDS) <= set(metric),
                f"query {query_id} metric {metric_id} is unavailable")
        selected_metrics.append({field: metric[field] for field in METRIC_FIELDS})

    role = query.get("role")
    question = None
    consumer = None
    if role == "PANEL":
        question = next((item for item in questions if isinstance(item, dict) and item.get("id") == query.get("question_id")), None)
        require(isinstance(question, dict), f"query {query_id} planned question is unavailable")
    else:
        consumer = next(
            (item for item in consumers if isinstance(item, dict) and item.get("role") == role and item.get("id") == query.get("consumer_id")),
            None,
        )
        require(isinstance(consumer, dict), f"query {query_id} planned consumer is unavailable")
    return {"query": query, "question": question, "consumer": consumer, "metrics": selected_metrics}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query_id", nargs="?", help="one query ID from --list")
    parser.add_argument("--list", action="store_true", help="list stable query IDs")
    parser.add_argument("--ticket", type=Path, default=Path("inbox/job.yaml"), help="ticket; defaults to inbox/job.yaml")
    args = parser.parse_args()
    try:
        require(args.list != (args.query_id is not None), "pass exactly one of --list or query_id")
        ticket, _, _, _, inputs, _ = stage.validate_ticket(args.ticket)
        require(ticket["agent"] == "promql-reviewer", "ticket is not for promql-reviewer")
        pack = stage.read_yaml(inputs["query-pack"])
        if args.list:
            payload: dict[str, Any] = {"query_ids": query_ids(pack)}
        else:
            payload = projection(pack, stage.read_yaml(inputs["metrics-contract"]),
                                 stage.read_yaml(inputs["dashboard-plan"]), args.query_id)
        print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    except (OSError, ReviewCapabilitiesError, stage.StageError, KeyError, TypeError) as error:
        print(f"FAIL query-review-capabilities: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
