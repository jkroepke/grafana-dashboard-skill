#!/usr/bin/env python3
"""Verify mandatory datasource/namespace/pod variable structure in rendered dashboards."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


class ContractError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def read_dashboard(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as error:
        raise ContractError("rendered dashboard is not readable valid JSON") from error
    require(isinstance(value, dict), "rendered dashboard root must be an object")
    return value


def named_variables(variables: Any) -> tuple[list[str], dict[str, dict[str, Any]]]:
    require(isinstance(variables, list), "dashboard variables must be an array")
    names: list[str] = []
    records: dict[str, dict[str, Any]] = {}
    for variable in variables:
        if not isinstance(variable, dict):
            continue
        spec = variable.get("spec")
        if not isinstance(spec, dict):
            continue
        name = spec.get("name")
        if not isinstance(name, str) or not name:
            continue
        require(name not in records, f"duplicate dashboard variable {name}")
        names.append(name)
        records[name] = variable
    for required in ("datasource", "namespace", "pod"):
        require(required in records, f"missing required {required} variable")
    require(names.index("datasource") < names.index("namespace") < names.index("pod"),
            "required variables are not in datasource, namespace, pod order")
    return names, records


def bool_field(spec: dict[str, Any], name: str, expected: bool, label: str) -> None:
    require(spec.get(name) is expected, f"{label}.{name} must be {str(expected).lower()}")


def verify_v2(root: dict[str, Any]) -> None:
    require(root.get("apiVersion") == "dashboard.grafana.app/v2",
            "dashboard apiVersion must be dashboard.grafana.app/v2")
    require(root.get("kind") == "Dashboard", "dashboard kind must be Dashboard")
    spec = root.get("spec")
    require(isinstance(spec, dict), "Dashboard V2 resource has no spec")
    _, records = named_variables(spec.get("variables"))

    datasource = records["datasource"]
    datasource_spec = datasource.get("spec")
    require(datasource.get("kind") == "DatasourceVariable", "datasource must be a DatasourceVariable")
    require(isinstance(datasource_spec, dict), "datasource variable has no spec")
    require(datasource_spec.get("pluginId") == "prometheus",
            "datasource variable must select the Prometheus plugin")
    bool_field(datasource_spec, "multi", False, "datasource")
    bool_field(datasource_spec, "includeAll", False, "datasource")

    for name, multi, include_all in (("namespace", False, False), ("pod", True, True)):
        variable = records[name]
        variable_spec = variable.get("spec")
        require(variable.get("kind") == "QueryVariable", f"{name} must be a QueryVariable")
        require(isinstance(variable_spec, dict), f"{name} variable has no spec")
        bool_field(variable_spec, "multi", multi, name)
        bool_field(variable_spec, "includeAll", include_all, name)
        query = variable_spec.get("query")
        require(isinstance(query, dict) and query.get("group") == "prometheus",
                f"{name} must use a Prometheus DataQuery")
        plugin_spec = query.get("spec")
        require(isinstance(plugin_spec, dict), f"{name} has no Prometheus query model")
        require(isinstance(plugin_spec.get("query"), str) and plugin_spec["query"],
                f"{name} Prometheus variable query is empty")
        require(isinstance(plugin_spec.get("qryType"), int)
                and not isinstance(plugin_spec.get("qryType"), bool),
                f"{name} Prometheus qryType is missing")
        require(isinstance(plugin_spec.get("refId"), str) and plugin_spec["refId"],
                f"{name} Prometheus editor refId is missing")
    require(records["pod"]["spec"].get("allValue") == "", "pod.allValue must be empty")
    pod_query = records["pod"]["spec"]["query"]["spec"]["query"]
    require("$namespace" in pod_query or "${namespace" in pod_query,
            "pod query must depend on namespace")


def verify(root: dict[str, Any]) -> None:
    verify_v2(root)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rendered_dashboard", type=Path)
    args = parser.parse_args()
    try:
        verify(read_dashboard(args.rendered_dashboard))
    except ContractError as error:
        print(f"FAIL {error}", file=sys.stderr)
        return 1
    print("PASS dashboard variable contract")
    return 0


if __name__ == "__main__":
    sys.exit(main())
