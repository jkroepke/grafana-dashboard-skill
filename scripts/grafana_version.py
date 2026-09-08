#!/usr/bin/env python3
"""Emit the configured Grafana /version response for the coordinator gate."""

from __future__ import annotations

import json
import sys

from grafana_access import AccessError, grafana_access_from_environment, grafana_url, http_request


def main() -> int:
    try:
        access = grafana_access_from_environment()
        response = http_request(access, "GET", grafana_url(access, "/version"))
        json.loads(response)
    except (AccessError, json.JSONDecodeError):
        return 1
    sys.stdout.buffer.write(response)
    return 0


if __name__ == "__main__":
    sys.exit(main())
