#!/usr/bin/env python3
"""Probe every observed application metric family through the configured datasource."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from grafana_access import AccessError, grafana_access_from_environment, grafana_env, http_request, prometheus_request_url, write_response
from metric_facts import FactsError, yaml_object


MAX_FAMILIES = 512
MAX_SUMMARY_BYTES = 64 * 1024
NAMESPACE_LABELS = ("namespace", "kubernetes_namespace")


class DiscoveryError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise DiscoveryError(message)


def snapshots(snapshot_dir: Path) -> list[dict[str, str]]:
    require(snapshot_dir.is_dir() and not snapshot_dir.is_symlink(), "snapshot directory is unavailable")
    items: list[dict[str, str]] = []
    families: set[str] = set()
    for path in sorted(snapshot_dir.glob("*.yaml")):
        if path.name == "manifest.yaml":
            continue
        record = yaml_object(path)
        require(record.get("kind") == "metric-family-snapshot", f"{path.name} is not a metric snapshot")
        identifier, family = record.get("id"), record.get("family")
        require(isinstance(identifier, str) and isinstance(family, str) and family, f"{path.name} is incomplete")
        require(family not in families, f"duplicate snapshot family: {family}")
        families.add(family)
        items.append({"id": identifier, "family": family})
    require(items, "no metric snapshots are available")
    require(len(items) <= MAX_FAMILIES, f"snapshot family count exceeds limit of {MAX_FAMILIES}")
    return items


def inspect(response: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(response)
    except json.JSONDecodeError:
        return {"result": "INVALID_RESPONSE", "series_count": 0, "label_keys": [], "namespace_label_keys": [], "namespace_candidates": []}
    if not isinstance(payload, dict) or payload.get("status") != "success" or not isinstance(payload.get("data"), list):
        return {"result": "API_ERROR", "series_count": 0, "label_keys": [], "namespace_label_keys": [], "namespace_candidates": []}
    series = [item for item in payload["data"] if isinstance(item, dict)]
    labels = sorted({key for item in series for key in item if isinstance(key, str)})
    namespace_label_keys = sorted({
        key for item in series for key in NAMESPACE_LABELS
        if isinstance(item.get(key), str) and item[key]
    })
    namespaces = sorted({
        item[key] for item in series for key in NAMESPACE_LABELS
        if isinstance(item.get(key), str) and item[key]
    })
    return {
        "result": "SERIES" if series else "EMPTY",
        "series_count": len(series),
        "label_keys": labels,
        "namespace_label_keys": namespace_label_keys,
        "namespace_candidates": namespaces,
    }


def completed_summary(output_dir: Path, items: list[dict[str, str]]) -> dict[str, Any]:
    require(output_dir.is_dir() and not output_dir.is_symlink(), "discovery output is not a directory")
    path = output_dir / "summary.json"
    require(path.is_file() and not path.is_symlink(), "discovery output is incomplete")
    try:
        summary = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DiscoveryError("discovery summary is invalid") from error
    require(isinstance(summary, dict), "discovery summary is invalid")
    require(summary.get("schema_version") == 1 and summary.get("kind") == "application-metric-discovery", "discovery summary is invalid")
    entries = summary.get("families")
    require(isinstance(entries, list), "discovery summary is invalid")
    expected = [(item["id"], item["family"]) for item in items]
    actual = [
        (entry.get("id"), entry.get("family")) if isinstance(entry, dict) else (None, None)
        for entry in entries
    ]
    require(actual == expected, "discovery summary does not match current snapshots")
    for item in items:
        for directory in ("requests", "responses"):
            evidence = output_dir / directory / f"{item['id']}.json"
            require(evidence.is_file() and not evidence.is_symlink(), "discovery evidence is incomplete")
    require(
        summary.get("family_count") == len(items)
        and isinstance(summary.get("populated_count"), int)
        and isinstance(summary.get("namespace_candidates"), list),
        "discovery summary is invalid",
    )
    return summary


def discover(snapshot_dir: Path, output_dir: Path, fetch: Callable[[dict[str, Any]], bytes]) -> dict[str, Any]:
    output_dir = output_dir if output_dir.is_absolute() else Path.cwd() / output_dir
    items = snapshots(snapshot_dir)
    if output_dir.exists():
        return completed_summary(output_dir, items)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".metric-discovery.", dir=output_dir.parent) as temporary:
        draft = Path(temporary)
        requests, responses = draft / "requests", draft / "responses"
        requests.mkdir()
        responses.mkdir()
        entries: list[dict[str, Any]] = []
        for item in items:
            request = {"operation": "series", "params": {"match[]": item["family"]}}
            request_path = requests / f"{item['id']}.json"
            response_path = responses / f"{item['id']}.json"
            request_path.write_text(json.dumps(request, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
            response = fetch(request)
            write_response(response_path, response)
            observed = inspect(response)
            # The request and response paths are deterministic from the snapshot ID.
            # Keep this index small; raw evidence remains in requests/ and responses/.
            entries.append({
                **item,
                "result": observed["result"],
                "series_count": observed["series_count"],
                "namespace_candidates": observed["namespace_candidates"],
                "namespace_label_keys": observed["namespace_label_keys"],
            })
        namespaces = sorted({value for entry in entries for value in entry["namespace_candidates"]})
        summary = {
            "schema_version": 1,
            "kind": "application-metric-discovery",
            "family_count": len(entries),
            "populated_count": sum(entry["result"] == "SERIES" for entry in entries),
            "namespace_candidates": namespaces,
            "families": entries,
        }
        encoded = json.dumps(summary, sort_keys=True, separators=(",", ":")) + "\n"
        require(len(encoded.encode("utf-8")) <= MAX_SUMMARY_BYTES, "discovery summary exceeds 64 KiB")
        (draft / "summary.json").write_text(encoded, encoding="utf-8")
        os.replace(draft, output_dir)
    return summary


def configured_fetch() -> Callable[[dict[str, Any]], bytes]:
    values = {**grafana_env(), **os.environ}
    require(values.get("WORKFLOW_DATASOURCE_ACCESS") == "true", "datasource access is not enabled")
    access = grafana_access_from_environment()
    return lambda request: http_request(access, "GET", prometheus_request_url(access, request))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-dir", type=Path, default=Path("records/pending"))
    parser.add_argument("--output-dir", type=Path, default=Path("evidence/metric-discovery"))
    args = parser.parse_args()
    try:
        summary = discover(args.snapshot_dir, args.output_dir, configured_fetch())
    except (OSError, AccessError, DiscoveryError, FactsError) as error:
        print(f"FAIL metrics-discovery: {error}", file=sys.stderr)
        return 1
    print(
        "PASS metrics-discovery "
        f"families={summary['family_count']} populated={summary['populated_count']} "
        f"namespace_candidates={len(summary['namespace_candidates'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
