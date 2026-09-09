#!/usr/bin/env python3
"""Stream the configured metrics target to standard output."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

from grafana_access import AccessError, grafana_env, require


def metrics_source() -> tuple[str, str, tuple[str, ...], bool]:
    values = grafana_env()
    target = values.get("METRICS_TARGET", "")
    parsed = urlsplit(target)
    is_url = parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    if not is_url:
        path = Path(target)
        require(path.is_file() and not path.is_symlink(), "METRICS_TARGET must be an HTTP(S) URL or regular local file")
        return str(path), "", (), False
    require(not parsed.fragment, "METRICS_TARGET URL must not contain a fragment")
    client = values.get("METRICS_HTTP_CLIENT", "curl")
    require(client, "METRICS_HTTP_CLIENT must not be empty for an HTTP(S) METRICS_TARGET")
    try:
        args = json.loads(values.get("METRICS_HTTP_CLIENT_ARGS_JSON", "[]"))
    except json.JSONDecodeError as error:
        raise AccessError("METRICS_HTTP_CLIENT_ARGS_JSON must be a JSON array") from error
    require(isinstance(args, list) and len(args) <= 16 and all(isinstance(arg, str) and len(arg) <= 1024 for arg in args),
            "METRICS_HTTP_CLIENT_ARGS_JSON must contain at most 16 short strings")
    executable = shutil.which(client) if "/" not in client else client
    require(executable is not None, "configured metrics HTTP client is unavailable")
    return target, executable, tuple(args), True


def main() -> int:
    try:
        target, client, args, is_url = metrics_source()
        if not is_url:
            with Path(target).open("rb") as source:
                shutil.copyfileobj(source, sys.stdout.buffer)
            return 0
        result = subprocess.run(
            [client, *args, "--fail", "--silent", "--show-error", "--connect-timeout", "10", "--max-time", "60", target],
            check=False,
        )
        require(result.returncode == 0, "metrics request failed")
        return 0
    except AccessError as error:
        print(f"ERROR metrics-reader: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
