#!/usr/bin/env python3
"""Require explicitly non-Prometheus dashboard consumers to remain byte-semantically unchanged."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import verify_query_parity as query_parity


class PreservationError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise PreservationError(message)


def read_dashboard(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as error:
        raise PreservationError("dashboard is not readable valid JSON") from error
    require(isinstance(value, dict), "dashboard root must be an object")
    return value


def v2_consumers(root: dict[str, Any]) -> dict[tuple[str, str, str], Any]:
    spec = root.get("spec")
    require(isinstance(spec, dict), "Dashboard V2 resource has no spec")
    result: dict[tuple[str, str, str], Any] = {}

    elements = spec.get("elements", {})
    require(isinstance(elements, dict), "Dashboard V2 elements must be an object")
    for element_name, panel in elements.items():
        if not isinstance(panel, dict) or panel.get("kind") != "Panel":
            continue
        panel_spec = panel.get("spec")
        data = panel_spec.get("data") if isinstance(panel_spec, dict) else None
        data_spec = data.get("spec") if isinstance(data, dict) else None
        queries = data_spec.get("queries", []) if isinstance(data_spec, dict) else []
        if not isinstance(queries, list):
            continue
        for index, wrapped in enumerate(queries):
            wrapped_spec = wrapped.get("spec") if isinstance(wrapped, dict) else None
            query = wrapped_spec.get("query") if isinstance(wrapped_spec, dict) else None
            group = query.get("group") if isinstance(query, dict) else None
            if not isinstance(group, str) or group == "prometheus":
                continue
            ref_id = wrapped_spec.get("refId")
            locator = ("PANEL", str(element_name), str(ref_id) if ref_id is not None else f"index-{index}")
            require(locator not in result, "duplicate non-Prometheus V2 panel consumer")
            result[locator] = wrapped

    variables = spec.get("variables", [])
    require(isinstance(variables, list), "Dashboard V2 variables must be an array")
    for index, variable in enumerate(variables):
        variable_spec = variable.get("spec") if isinstance(variable, dict) else None
        query = variable_spec.get("query") if isinstance(variable_spec, dict) else None
        group = query.get("group") if isinstance(query, dict) else None
        if not isinstance(group, str) or group == "prometheus":
            continue
        name = variable_spec.get("name")
        locator = ("VARIABLE", str(name) if name is not None else f"index-{index}", group)
        require(locator not in result, "duplicate non-Prometheus V2 variable consumer")
        result[locator] = variable

    annotations = spec.get("annotations", [])
    require(isinstance(annotations, list), "Dashboard V2 annotations must be an array")
    for index, annotation in enumerate(annotations):
        annotation_spec = annotation.get("spec") if isinstance(annotation, dict) else None
        query = annotation_spec.get("query") if isinstance(annotation_spec, dict) else None
        group = query.get("group") if isinstance(query, dict) else None
        if not isinstance(group, str) or group == "prometheus":
            continue
        name = annotation_spec.get("name")
        locator = ("ANNOTATION", str(name) if name is not None else f"index-{index}", group)
        require(locator not in result, "duplicate non-Prometheus V2 annotation consumer")
        result[locator] = annotation
    return result


def classic_consumers(root: dict[str, Any]) -> dict[tuple[str, str, str], Any]:
    if isinstance(root.get("dashboard"), dict):
        root = root["dashboard"]
    result: dict[tuple[str, str, str], Any] = {}
    for panel in query_parity.walk_classic_panels(root.get("panels")):
        panel_id = panel.get("id")
        for index, target in enumerate(panel.get("targets", [])):
            if not isinstance(target, dict) or not query_parity.explicitly_non_prometheus(
                target.get("datasource"), panel.get("datasource")
            ):
                continue
            ref_id = target.get("refId")
            locator = ("PANEL", f"panel-{panel_id}", str(ref_id) if ref_id is not None else f"index-{index}")
            require(locator not in result, "duplicate non-Prometheus classic panel consumer")
            result[locator] = {
                "target": target,
                "effective_datasource": target.get("datasource", panel.get("datasource")),
            }

    templating = root.get("templating", {})
    variables = templating.get("list", []) if isinstance(templating, dict) else []
    for index, variable in enumerate(variables):
        if not isinstance(variable, dict) or not query_parity.explicitly_non_prometheus(
            variable.get("datasource")
        ):
            continue
        name = variable.get("name")
        locator = ("VARIABLE", str(name) if name is not None else f"index-{index}", "datasource")
        require(locator not in result, "duplicate non-Prometheus classic variable consumer")
        result[locator] = variable

    annotations = root.get("annotations", {})
    annotation_list = annotations.get("list", []) if isinstance(annotations, dict) else []
    for index, annotation in enumerate(annotation_list):
        if not isinstance(annotation, dict) or not query_parity.explicitly_non_prometheus(
            annotation.get("datasource")
        ):
            continue
        name = annotation.get("name")
        locator = ("ANNOTATION", str(name) if name is not None else f"index-{index}", "datasource")
        require(locator not in result, "duplicate non-Prometheus classic annotation consumer")
        result[locator] = annotation
    return result


def consumers(root: dict[str, Any]) -> dict[tuple[str, str, str], Any]:
    if isinstance(root.get("spec"), dict) and isinstance(root["spec"].get("elements"), dict):
        return v2_consumers(root)
    return classic_consumers(root)


def verify(candidate: dict[str, Any], baseline: dict[str, Any] | None) -> None:
    after = consumers(candidate)
    if baseline is None:
        require(not after, "new dashboards cannot add non-Prometheus consumers in this workflow")
        return
    before = consumers(baseline)
    require(before == after, "explicitly non-Prometheus consumers changed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args()
    try:
        candidate = read_dashboard(args.candidate)
        baseline = read_dashboard(args.baseline) if args.baseline is not None else None
        verify(candidate, baseline)
    except PreservationError as error:
        print(f"FAIL {error}", file=sys.stderr)
        return 1
    print("PASS non-Prometheus consumer preservation")
    return 0


if __name__ == "__main__":
    sys.exit(main())
