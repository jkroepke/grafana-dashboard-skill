#!/usr/bin/env python3
"""Compile an allowlisted, typed PromQL template request into exact query text.

This intentionally accepts semantics as input.  It never guesses whether a
metric is a counter from its name; requests outside the small template set are
rejected and must use the custom-query review path.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


NAME = re.compile(r"^[A-Za-z_:][A-Za-z0-9_:]*$")
LABEL = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
TYPE = {"counter", "gauge", "histogram"}


class TemplateError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise TemplateError(message)


def read_request(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as error:
        raise TemplateError("template request must be a JSON object") from error
    require(isinstance(value, dict), "template request must be a JSON object")
    return value


def string(value: Any, field: str, pattern: re.Pattern[str] | None = None) -> str:
    require(isinstance(value, str) and value, f"{field} must be a non-empty string")
    require(len(value) <= 4096, f"{field} is too long")
    if pattern is not None:
        require(pattern.fullmatch(value) is not None, f"{field} is invalid")
    return value


def labels(value: Any) -> list[str]:
    require(isinstance(value, list) and value, "group_by must be a non-empty array")
    result = [string(item, "group_by item", LABEL) for item in value]
    require(len(result) <= 8 and len(set(result)) == len(result), "group_by is invalid")
    return result


def label(request: dict[str, Any]) -> str:
    return string(request.get("label"), "label", LABEL)


def selector(value: Any) -> str:
    if value is None:
        return ""
    result = string(value, "selector")
    # Grafana placeholders such as ${pod:regex} are valid inside a selector;
    # raw braces are not, because this function owns the outer selector braces.
    remaining = re.sub(r"\$\{[^{}\n]{1,128}\}", "", result)
    require("{" not in remaining and "}" not in remaining and "\n" not in result, "selector is invalid")
    return "{" + result + "}"


def metric(request: dict[str, Any], field: str = "metric") -> str:
    return string(request.get(field), field, NAME)


def metric_type(request: dict[str, Any], field: str = "metric_type") -> str:
    value = string(request.get(field), field)
    require(value in TYPE, f"{field} is unsupported")
    return value


def rate_expression(request: dict[str, Any], metric_field: str = "metric") -> str:
    require(metric_type(request, metric_field + "_type" if metric_field != "metric" else "metric_type") == "counter",
            "rate templates require an explicitly declared counter")
    window = string(request.get("window"), "window")
    require("[" not in window and "]" not in window and "\n" not in window, "window is invalid")
    return f"rate({metric(request, metric_field)}{selector(request.get(metric_field + '_selector', request.get('selector')))}[{window}])"


def compile_template(request: dict[str, Any]) -> dict[str, Any]:
    template = string(request.get("template"), "template")
    if template == "namespace_variable":
        output_label = label(request)
        expression = f"label_values({metric(request)}{selector(request.get('selector'))}, {output_label})"
        mode, identity = "VARIABLE", [output_label]
    elif template == "pod_variable":
        output_label = label(request)
        expression = f"label_values({metric(request)}{selector(request.get('selector'))}, {output_label})"
        mode, identity = "VARIABLE", [output_label]
    elif template in {"counter_rate_by_pod", "restart_rate"}:
        group_by = labels(request.get("group_by", ["pod"]))
        expression = f"sum by ({', '.join(group_by)}) ({rate_expression(request)})"
        mode, identity = "RANGE", group_by
    elif template == "gauge_by_pod":
        require(metric_type(request) == "gauge", "gauge template requires an explicitly declared gauge")
        group_by = labels(request.get("group_by", ["pod"]))
        expression = f"max by ({', '.join(group_by)}) ({metric(request)}{selector(request.get('selector'))})"
        mode, identity = "RANGE", group_by
    elif template == "histogram_quantile":
        require(metric_type(request) == "histogram", "histogram template requires an explicitly declared histogram")
        quantile = string(request.get("quantile"), "quantile")
        try:
            require(0 < float(quantile) < 1, "quantile must be between zero and one")
        except ValueError as error:
            raise TemplateError("quantile must be numeric") from error
        group_by = labels(request.get("group_by", ["pod"]))
        window = string(request.get("window"), "window")
        bucket = metric(request, "bucket_metric")
        expression = (
            f"histogram_quantile({quantile}, sum by (le, {', '.join(group_by)}) "
            f"(rate({bucket}{selector(request.get('selector'))}[{window}])))"
        )
        mode, identity = "RANGE", group_by
    elif template in {"container_cpu_ratio", "container_memory_ratio", "pod_ready"}:
        # These need joins or exporter-specific label conventions.  Keeping them
        # out of the generic compiler is safer than silently choosing one.
        raise TemplateError(f"{template} requires template CUSTOM with reviewed semantics")
    else:
        raise TemplateError("unknown template; use CUSTOM for non-standard PromQL")
    return {"template": template, "expression": expression, "mode": mode, "result_identity": identity}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", type=Path, help="small JSON template request")
    parser.add_argument("output", type=Path, help="new JSON result path")
    args = parser.parse_args()
    try:
        require(not args.output.exists(), "output already exists")
        result = compile_template(read_request(args.request))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    except (OSError, TemplateError) as error:
        print(f"FAIL promql-templates: {error}", file=sys.stderr)
        return 1
    print("PASS promql-templates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
