#!/usr/bin/env python3
"""Validate one Dashboard Schema V2 resource through the configured Grafana."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import quote

from grafana_access import (
    AccessError,
    grafana_access_from_environment,
    grafana_url,
    http_request,
    read_json_file,
    write_response,
)


DRY_RUN_PATH = "/apis/dashboard.grafana.app/v2/namespaces/default/dashboards?dryRun=All&fieldValidation=Strict"
RESOURCE_PATH = "/apis/dashboard.grafana.app/v2/namespaces/default/dashboards/{}?dryRun=All&fieldValidation=Strict"


def replacement(resource: dict, live: bytes, request_path: Path) -> str:
    """Write the exact update envelope, retaining live resource identity metadata."""
    try:
        current = json.loads(live)
    except json.JSONDecodeError as error:
        raise AccessError("existing dashboard response is not valid JSON") from error
    if not isinstance(current, dict) or not isinstance(current.get("metadata"), dict):
        raise AccessError("existing dashboard response has no metadata")
    if not isinstance(resource.get("spec"), dict):
        raise AccessError("dashboard resource has no spec")
    live_metadata = current["metadata"]
    name = live_metadata.get("name")
    if not isinstance(name, str) or not name:
        raise AccessError("existing dashboard has no resource name")
    candidate_name = resource.get("metadata", {}).get("name") if isinstance(resource.get("metadata"), dict) else None
    if candidate_name is not None and candidate_name != name:
        raise AccessError("candidate dashboard name differs from existing resource")
    # Keep only replacement-relevant live metadata.  Echoing arbitrary managed
    # fields back to an API server is neither required nor reliably accepted.
    metadata = {key: live_metadata[key] for key in ("name", "namespace", "resourceVersion", "annotations") if key in live_metadata}
    body = {"apiVersion": resource.get("apiVersion"), "kind": resource.get("kind"), "metadata": metadata, "spec": resource["spec"]}
    if not isinstance(body["apiVersion"], str) or not isinstance(body["kind"], str):
        raise AccessError("dashboard resource has no apiVersion or kind")
    request_path.write_text(json.dumps(body, separators=(",", ":")), encoding="utf-8")
    return name


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("resource_file", type=Path)
    parser.add_argument("response_file", type=Path)
    parser.add_argument("--operation", choices=("CREATE", "UPDATE"), default="CREATE")
    args = parser.parse_args()
    try:
        resource = read_json_file(args.resource_file, "resource")
        access = grafana_access_from_environment()
        request_file = args.resource_file
        url = grafana_url(access, DRY_RUN_PATH)
        temporary_request: Path | None = None
        if args.operation == "UPDATE":
            name = resource.get("metadata", {}).get("name") if isinstance(resource.get("metadata"), dict) else None
            if not isinstance(name, str) or not name:
                raise AccessError("UPDATE requires resource metadata.name")
            live = http_request(
                access, "GET", grafana_url(access, RESOURCE_PATH.format(quote(name, safe=""))), expected_status=200,
            )
            temporary_request = args.response_file.with_name(f".{args.response_file.name}.update-request.json")
            if temporary_request.exists():
                raise AccessError("temporary update request already exists")
            replacement(resource, live, temporary_request)
            request_file = temporary_request
            url = grafana_url(access, RESOURCE_PATH.format(quote(name, safe="")))
        response = http_request(
            access,
            "POST" if args.operation == "CREATE" else "PUT",
            url,
            request_file=request_file,
            headers=("Content-Type: application/json",),
            expected_status=(200, 201),
        )
        write_response(args.response_file, response)
        if temporary_request is not None:
            temporary_request.unlink()
    except AccessError as error:
        print(f"FAIL {error}", file=sys.stderr)
        return 1
    print("PASS grafana-dry-run")
    return 0


if __name__ == "__main__":
    sys.exit(main())
