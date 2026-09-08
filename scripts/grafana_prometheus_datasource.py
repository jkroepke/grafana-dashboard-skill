#!/usr/bin/env python3
"""Resolve the configured/default Prometheus datasource UID privately."""

from __future__ import annotations

import sys

from grafana_access import AccessError, grafana_access_from_environment, prometheus_datasource_uid


def main() -> int:
    try:
        print(prometheus_datasource_uid(grafana_access_from_environment()))
    except AccessError:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
