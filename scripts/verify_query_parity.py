#!/usr/bin/env python3
"""Verify approved queries at their exact rendered Prometheus consumers."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Optional


Locator = tuple[str, str, Optional[str]]


@dataclass(frozen=True)
class Consumer:
    expression: str
    mode: str
    datasource_ref: str
    qry_type: Optional[int] = None


class ParityError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ParityError(message)


def read_json(path: Path) -> tuple[bytes, dict[str, Any]]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, json.JSONDecodeError) as error:
        raise ParityError(f"cannot read valid JSON from {path}: {error}") from error
    require(isinstance(value, dict), f"{path} root must be an object")
    return raw, value


def sha256(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def locator_fingerprint(locator: Locator) -> str:
    encoded = "\0".join("" if value is None else value for value in locator)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:12]


def datasource_ref(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    if isinstance(value, dict):
        for key in ("name", "uid"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate:
                return candidate
    return None


def add_consumer(consumers: dict[Locator, Consumer], locator: Locator, consumer: Consumer) -> None:
    require(locator not in consumers,
            f"duplicate rendered consumer locator fingerprint={locator_fingerprint(locator)}")
    consumers[locator] = consumer


def v2_consumers(root: dict[str, Any]) -> dict[Locator, Consumer]:
    spec = root.get("spec")
    require(isinstance(spec, dict), "Dashboard V2 resource has no spec object")
    consumers: dict[Locator, Consumer] = {}

    elements = spec.get("elements")
    require(isinstance(elements, dict), "Dashboard V2 resource has no elements object")
    for element_name, panel in elements.items():
        if not isinstance(panel, dict) or panel.get("kind") != "Panel":
            continue
        panel_spec = panel.get("spec")
        data = panel_spec.get("data") if isinstance(panel_spec, dict) else None
        data_spec = data.get("spec") if isinstance(data, dict) else None
        queries = data_spec.get("queries", []) if isinstance(data_spec, dict) else []
        require(isinstance(queries, list), "Dashboard V2 panel queries must be an array")
        for wrapped in queries:
            require(isinstance(wrapped, dict), "Dashboard V2 PanelQuery must be an object")
            wrapped_spec = wrapped.get("spec")
            require(isinstance(wrapped_spec, dict), "Dashboard V2 PanelQuery has no spec")
            query = wrapped_spec.get("query")
            require(isinstance(query, dict), "Dashboard V2 PanelQuery has no DataQuery")
            if query.get("group") != "prometheus":
                continue
            query_spec = query.get("spec")
            require(isinstance(query_spec, dict), "Prometheus DataQuery has no spec")
            expression = query_spec.get("expr")
            require(isinstance(expression, str) and expression, "Prometheus panel query has no expr")
            ref_id = wrapped_spec.get("refId")
            require(isinstance(ref_id, str) and ref_id, "Prometheus panel query has no refId")
            ds_ref = datasource_ref(query.get("datasource"))
            require(ds_ref is not None, "Prometheus panel query has no datasource reference")
            mode = "INSTANT" if query_spec.get("instant") is True else "RANGE"
            add_consumer(consumers, ("PANEL", str(element_name), ref_id), Consumer(expression, mode, ds_ref))

    variables = spec.get("variables", [])
    require(isinstance(variables, list), "Dashboard V2 variables must be an array")
    for variable in variables:
        if not isinstance(variable, dict) or variable.get("kind") != "QueryVariable":
            continue
        variable_spec = variable.get("spec")
        require(isinstance(variable_spec, dict), "QueryVariable has no spec")
        query = variable_spec.get("query")
        require(isinstance(query, dict), "QueryVariable has no DataQuery")
        if query.get("group") != "prometheus":
            continue
        plugin_spec = query.get("spec")
        require(isinstance(plugin_spec, dict), "Prometheus variable query has no plugin spec")
        expression = plugin_spec.get("query")
        require(isinstance(expression, str) and expression, "Prometheus variable query is empty")
        ref_id = plugin_spec.get("refId")
        require(ref_id is None or isinstance(ref_id, str), "Prometheus variable refId is invalid")
        qry_type = plugin_spec.get("qryType")
        require(isinstance(qry_type, int) and not isinstance(qry_type, bool),
                "Prometheus variable qryType is invalid")
        name = variable_spec.get("name")
        require(isinstance(name, str) and name, "QueryVariable has no name")
        ds_ref = datasource_ref(query.get("datasource"))
        require(ds_ref is not None, "Prometheus variable query has no datasource reference")
        add_consumer(
            consumers,
            ("VARIABLE", name, ref_id),
            Consumer(expression, "VARIABLE", ds_ref, qry_type),
        )

    annotations = spec.get("annotations", [])
    require(isinstance(annotations, list), "Dashboard V2 annotations must be an array")
    for annotation in annotations:
        if not isinstance(annotation, dict):
            continue
        annotation_spec = annotation.get("spec")
        if not isinstance(annotation_spec, dict):
            continue
        query = annotation_spec.get("query")
        if not isinstance(query, dict) or query.get("group") != "prometheus":
            continue
        plugin_spec = query.get("spec")
        require(isinstance(plugin_spec, dict), "Prometheus annotation has no plugin spec")
        expression = plugin_spec.get("expr")
        require(isinstance(expression, str) and expression, "Prometheus annotation has no expr")
        ref_id = plugin_spec.get("refId")
        require(ref_id is None or isinstance(ref_id, str), "Prometheus annotation refId is invalid")
        name = annotation_spec.get("name")
        require(isinstance(name, str) and name, "Prometheus annotation has no name")
        ds_ref = datasource_ref(query.get("datasource"))
        require(ds_ref is not None, "Prometheus annotation has no datasource reference")
        add_consumer(consumers, ("ANNOTATION", name, ref_id), Consumer(expression, "RANGE", ds_ref))
    return consumers


def walk_classic_panels(panels: Any) -> Iterator[dict[str, Any]]:
    if not isinstance(panels, list):
        return
    for panel in panels:
        if not isinstance(panel, dict):
            continue
        yield panel
        yield from walk_classic_panels(panel.get("panels"))


def explicitly_non_prometheus(*values: Any) -> bool:
    """Return true only when the nearest supplied datasource declares another type."""
    for value in values:
        if value is None:
            continue
        if isinstance(value, dict):
            datasource_type = value.get("type")
            if isinstance(datasource_type, str) and datasource_type:
                return datasource_type.lower() != "prometheus"
            reference = datasource_ref(value)
        else:
            reference = datasource_ref(value)
        if reference in {"$datasource", "${datasource}"}:
            return False
    return False


def classic_consumers(root: dict[str, Any]) -> dict[Locator, Consumer]:
    if isinstance(root.get("dashboard"), dict):
        root = root["dashboard"]
    consumers: dict[Locator, Consumer] = {}
    for panel in walk_classic_panels(root.get("panels")):
        panel_id = panel.get("id")
        require(isinstance(panel_id, int), "classic Prometheus panel requires numeric id")
        panel_name = f"panel-{panel_id}"
        for target in panel.get("targets", []):
            if not isinstance(target, dict):
                continue
            if explicitly_non_prometheus(target.get("datasource"), panel.get("datasource")):
                continue
            expression = target.get("expr")
            if not isinstance(expression, str) or not expression:
                continue
            ref_id = target.get("refId")
            require(isinstance(ref_id, str) and ref_id, "classic Prometheus target has no refId")
            ds_ref = datasource_ref(target.get("datasource")) or datasource_ref(panel.get("datasource"))
            require(ds_ref is not None, "classic Prometheus target has no datasource reference")
            mode = "INSTANT" if target.get("instant") is True else "RANGE"
            add_consumer(consumers, ("PANEL", panel_name, ref_id), Consumer(expression, mode, ds_ref))

    templating = root.get("templating", {})
    variables = templating.get("list", []) if isinstance(templating, dict) else []
    for variable in variables:
        if not isinstance(variable, dict) or variable.get("type") != "query":
            continue
        if explicitly_non_prometheus(variable.get("datasource")):
            continue
        raw_query = variable.get("query")
        if isinstance(raw_query, dict):
            expression = raw_query.get("query")
            ref_id = raw_query.get("refId")
            qry_type = raw_query.get("qryType")
        else:
            expression = raw_query
            ref_id = variable.get("refId")
            qry_type = None
        if not isinstance(expression, str) or not expression:
            continue
        require(ref_id is None or isinstance(ref_id, str), "classic variable refId is invalid")
        name = variable.get("name")
        require(isinstance(name, str) and name, "classic query variable has no name")
        ds_ref = datasource_ref(variable.get("datasource"))
        require(ds_ref is not None, "classic query variable has no datasource reference")
        require(qry_type is None or (isinstance(qry_type, int) and not isinstance(qry_type, bool)),
                "classic variable qryType is invalid")
        add_consumer(
            consumers,
            ("VARIABLE", name, ref_id),
            Consumer(expression, "VARIABLE", ds_ref, qry_type),
        )

    annotations = root.get("annotations", {})
    annotation_list = annotations.get("list", []) if isinstance(annotations, dict) else []
    for annotation in annotation_list:
        if not isinstance(annotation, dict):
            continue
        if explicitly_non_prometheus(annotation.get("datasource")):
            continue
        expression = annotation.get("expr")
        if not isinstance(expression, str) or not expression:
            continue
        name = annotation.get("name")
        require(isinstance(name, str) and name, "classic Prometheus annotation has no name")
        ref_id = annotation.get("refId")
        require(ref_id is None or isinstance(ref_id, str), "classic annotation refId is invalid")
        ds_ref = datasource_ref(annotation.get("datasource"))
        require(ds_ref is not None, "classic annotation has no datasource reference")
        add_consumer(consumers, ("ANNOTATION", name, ref_id), Consumer(expression, "RANGE", ds_ref))
    return consumers


def approved_consumers(pack: dict[str, Any]) -> tuple[dict[Locator, Consumer], dict[Locator, str]]:
    require(pack.get("artifact_type") == "query-pack" and pack.get("status") == "PASS",
            "query pack must be a PASS query-pack artifact")
    records = pack.get("queries")
    require(isinstance(records, list) and records, "query pack must contain queries")
    consumers: dict[Locator, Consumer] = {}
    ids: dict[Locator, str] = {}
    for record in records:
        require(isinstance(record, dict), "query pack record must be an object")
        locator = record.get("consumer_locator")
        require(isinstance(locator, dict), "query pack record has no consumer_locator")
        key = (locator.get("kind"), locator.get("name"), locator.get("ref_id"))
        require(all(isinstance(value, str) for value in key[:2]), "query locator kind/name is invalid")
        require(key[2] is None or isinstance(key[2], str), "query locator ref_id is invalid")
        require(key not in consumers, f"duplicate approved locator fingerprint={locator_fingerprint(key)}")
        expression = record.get("expression")
        mode = record.get("mode")
        ds_ref = record.get("datasource_ref")
        plugin_model = record.get("plugin_query_model")
        require(isinstance(expression, str) and expression, "approved expression is empty")
        require(isinstance(mode, str) and isinstance(ds_ref, str) and ds_ref,
                "approved query mode/datasource is invalid")
        if key[0] == "VARIABLE":
            require(isinstance(plugin_model, dict), "approved variable has no plugin_query_model")
            qry_type = plugin_model.get("qry_type")
            require(qry_type is None or (isinstance(qry_type, int) and not isinstance(qry_type, bool)),
                    "approved variable qry_type is invalid")
            require(plugin_model.get("editor_ref_id") == key[2],
                    "approved variable editor ref does not match locator")
        else:
            require(plugin_model is None, "non-variable query has plugin_query_model")
            qry_type = None
        consumers[key] = Consumer(expression, mode, ds_ref, qry_type)
        ids[key] = str(record.get("id"))
    return consumers, ids


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query_pack", type=Path)
    parser.add_argument("query_review", type=Path)
    parser.add_argument("rendered_dashboard", type=Path)
    args = parser.parse_args()
    try:
        pack_raw, pack = read_json(args.query_pack)
        _, review = read_json(args.query_review)
        _, rendered = read_json(args.rendered_dashboard)
        require(review.get("artifact_type") == "query-review" and review.get("status") == "PASS",
                "query review must be a PASS query-review artifact")
        require(review.get("query_pack_sha256") == sha256(pack_raw),
                "query review does not approve the current query pack")
        require(review.get("inputs", {}).get("query-pack") == sha256(pack_raw),
                "query-review input digest does not match query pack")
        require(review.get("findings") == [], "PASS query review must have zero findings")

        expected, query_ids = approved_consumers(pack)
        if isinstance(rendered.get("spec"), dict) and isinstance(rendered["spec"].get("elements"), dict):
            actual = v2_consumers(rendered)
        else:
            actual = classic_consumers(rendered)

        missing = set(expected) - set(actual)
        extra = set(actual) - set(expected)
        if missing or extra:
            missing_ids = ",".join(locator_fingerprint(item) for item in sorted(missing, key=str))
            extra_ids = ",".join(locator_fingerprint(item) for item in sorted(extra, key=str))
            raise ParityError(f"consumer mismatch missing=[{missing_ids}] extra=[{extra_ids}]")

        mismatches: list[str] = []
        for locator, approved in expected.items():
            rendered_consumer = actual[locator]
            changed = []
            if rendered_consumer.expression != approved.expression:
                changed.append("expression")
            if rendered_consumer.mode != approved.mode:
                changed.append("mode")
            if rendered_consumer.datasource_ref != approved.datasource_ref:
                changed.append("datasource")
            if rendered_consumer.qry_type != approved.qry_type:
                changed.append("qryType")
            if changed:
                mismatches.append(f"{query_ids[locator]}:{'+'.join(changed)}")
        require(not mismatches, "query consumer mismatch " + ",".join(mismatches))
    except ParityError as error:
        print(f"FAIL {error}", file=sys.stderr)
        return 1
    print(f"PASS query parity count={len(expected)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
