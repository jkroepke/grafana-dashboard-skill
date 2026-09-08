#!/usr/bin/env python3
"""Validate one Dashboard Schema V2 resource through the configured Grafana."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from grafana_access import (
    AccessError,
    grafana_access_from_environment,
    grafana_url,
    http_request,
    read_json_file,
    write_response,
)


DRY_RUN_PATH = "/apis/dashboard.grafana.app/v2/namespaces/default/dashboards?dryRun=All&fieldValidation=Strict"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("resource_file", type=Path)
    parser.add_argument("response_file", type=Path)
    args = parser.parse_args()
    try:
        read_json_file(args.resource_file, "resource")
        access = grafana_access_from_environment()
        response = http_request(
            access,
            "POST",
            grafana_url(access, DRY_RUN_PATH),
            request_file=args.resource_file,
            headers=("Content-Type: application/json",),
            expected_status=(200, 201),
        )
        write_response(args.response_file, response)
    except AccessError as error:
        print(f"FAIL {error}", file=sys.stderr)
        return 1
    print("PASS grafana-dry-run")
    return 0


if __name__ == "__main__":
    sys.exit(main())
