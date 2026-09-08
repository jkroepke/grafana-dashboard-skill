#!/usr/bin/env python3
"""Execute an allowlisted read-only Prometheus request through Grafana."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from grafana_access import (
    AccessError,
    grafana_access_from_environment,
    http_request,
    prometheus_request_url,
    read_json_file,
    write_response,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request_file", type=Path)
    parser.add_argument("response_file", type=Path)
    args = parser.parse_args()
    try:
        access = grafana_access_from_environment()
        request = read_json_file(args.request_file, "request")
        response = http_request(access, "GET", prometheus_request_url(access, request))
        write_response(args.response_file, response)
    except AccessError as error:
        print(f"FAIL {error}", file=sys.stderr)
        return 1
    print("PASS prometheus-reader")
    return 0


if __name__ == "__main__":
    sys.exit(main())
