"""Grafana access helpers for capability-specific wrappers."""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote, urlencode, urlsplit, urlunsplit


UID_RE = re.compile(r"^[A-Za-z0-9_-]{1,160}$")
LABEL_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
PARAMETER_RE = re.compile(r"^[A-Za-z0-9_.\[\]-]{1,64}$")
ENV_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
ENV_KEYS = frozenset({
    "GRAFANA_TARGET",
    "GRAFANA_HTTP_CLIENT",
    "GRAFANA_HTTP_CLIENT_ARGS_JSON",
    "GRAFANA_PROMETHEUS_DATASOURCE_UID",
    "METRICS_TARGET",
    "METRICS_HTTP_CLIENT",
    "METRICS_HTTP_CLIENT_ARGS_JSON",
    "WORKFLOW_RUN_ID",
    "WORKFLOW_DATASOURCE_ACCESS",
    "WORKFLOW_DASHBOARD_API_VALIDATION",
    "WORKFLOW_PUBLISH_REQUESTED",
})


class AccessError(ValueError):
    """Raised when a configured Grafana access capability cannot be used."""


@dataclass(frozen=True)
class GrafanaAccess:
    """Trusted runtime configuration for the Grafana wrappers."""

    target: str
    client: str
    client_args: tuple[str, ...]
    prometheus_datasource_uid: str | None


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AccessError(message)


def workflow_env_path(cwd: Path | None = None) -> Path | None:
    """Find the project workspace configuration for the current workflow."""
    directory = (cwd or Path.cwd()).resolve()
    for candidate in (directory, *directory.parents):
        if candidate.name == "workspace" and candidate.parent.parent.name == "dashboards":
            return candidate / ".env"
    return None


def grafana_env(path: Path | None = None) -> dict[str, str]:
    """Load the Grafana configuration for the active workspace."""
    path = path or workflow_env_path()
    if path is None:
        return {}
    if not path.exists():
        return {}
    require(path.is_file() and not path.is_symlink(), "Grafana .env must be a regular file")
    require(stat.S_IMODE(path.stat().st_mode) & 0o077 == 0, "Grafana .env must not be group/world accessible")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise AccessError("Grafana .env could not be read") from error
    values: dict[str, str] = {}
    for number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        require(separator and ENV_KEY_RE.fullmatch(key) is not None, f"Grafana .env line {number} is invalid")
        require(key in ENV_KEYS, f"Grafana .env key {key} is not allowed")
        require(key not in values and "\x00" not in value, f"Grafana .env line {number} is invalid")
        values[key] = value
    return values


def write_workflow_env(path: Path, values: Mapping[str, str]) -> None:
    """Atomically replace the private workspace configuration."""
    require(set(values).issubset(ENV_KEYS), "Grafana .env key is not allowed")
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, prefix=".env.", delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            os.chmod(temporary_path, 0o600)
            for key in sorted(values):
                temporary.write(f"{key}={values[key]}\n")
        os.replace(temporary_path, path)
    except OSError as error:
        raise AccessError("Grafana .env could not be written") from error


def grafana_access_from_environment(
    environment: Mapping[str, str] | None = None,
    *,
    env_path: Path | None = None,
) -> GrafanaAccess:
    """Load workspace configuration, allowing process environment overrides."""
    values = {**grafana_env(env_path), **(os.environ if environment is None else environment)}
    target = values.get("GRAFANA_TARGET", "")
    parsed = urlsplit(target)
    require(
        parsed.scheme in {"http", "https"} and bool(parsed.netloc)
        and not parsed.query and not parsed.fragment,
        "GRAFANA_TARGET must be an HTTP(S) base URL without query or fragment",
    )
    client = values.get("GRAFANA_HTTP_CLIENT", "curl")
    require(bool(client), "GRAFANA_HTTP_CLIENT must not be empty")
    raw_args = values.get("GRAFANA_HTTP_CLIENT_ARGS_JSON", "[]")
    try:
        client_args = json.loads(raw_args)
    except json.JSONDecodeError as error:
        raise AccessError("GRAFANA_HTTP_CLIENT_ARGS_JSON must be a JSON array") from error
    require(isinstance(client_args, list), "GRAFANA_HTTP_CLIENT_ARGS_JSON must be a JSON array")
    require(
        len(client_args) <= 16 and all(isinstance(value, str) and len(value) <= 1024 for value in client_args),
        "GRAFANA_HTTP_CLIENT_ARGS_JSON must contain at most 16 short strings",
    )
    uid = values.get("GRAFANA_PROMETHEUS_DATASOURCE_UID")
    require(uid is None or UID_RE.fullmatch(uid) is not None, "configured datasource UID is invalid")
    return GrafanaAccess(target, client, tuple(client_args), uid)


def grafana_url(access: GrafanaAccess, path: str) -> str:
    """Append a fixed Grafana path to the configured base URL."""
    require(path.startswith("/"), "Grafana API path must start with a slash")
    path_part, separator, query = path.partition("?")
    require(not separator or "#" not in query, "Grafana API query is invalid")
    parsed = urlsplit(access.target)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/") + path_part, query, ""))


def http_request(
    access: GrafanaAccess,
    method: str,
    url: str,
    *,
    request_file: Path | None = None,
    headers: tuple[str, ...] = (),
    expected_status: int | tuple[int, ...] = 200,
) -> bytes:
    """Run the configured HTTP client and return only an expected-status body."""
    client = shutil.which(access.client) if "/" not in access.client else access.client
    require(client is not None, "configured Grafana HTTP client is unavailable")
    if request_file is not None:
        require(request_file.is_file() and not request_file.is_symlink(), "request file must be regular")
    with tempfile.TemporaryDirectory(prefix="grafana-access-") as temporary:
        response_file = Path(temporary) / "response"
        command = [
            client,
            *access.client_args,
            "--silent",
            "--show-error",
            "--connect-timeout",
            "10",
            "--max-time",
            "60",
            "--request",
            method,
            "--output",
            str(response_file),
            "--write-out",
            "%{http_code}",
        ]
        for header in headers:
            command.extend(["--header", header])
        if request_file is not None:
            command.extend(["--data-binary", f"@{request_file}"])
        command.append(url)
        try:
            result = subprocess.run(command, capture_output=True, check=False)
        except OSError as error:
            raise AccessError("configured Grafana HTTP client could not run") from error
        require(result.returncode == 0, "Grafana request failed")
        status = result.stdout.decode("ascii", errors="replace").strip()
        expected = (expected_status,) if isinstance(expected_status, int) else expected_status
        require(
            status in {str(value) for value in expected},
            f"Grafana request returned HTTP {status or 'unknown'}",
        )
        try:
            return response_file.read_bytes()
        except OSError as error:
            raise AccessError("Grafana response could not be read") from error


def prometheus_datasource_uid(access: GrafanaAccess) -> str:
    """Return the configured or selected Prometheus datasource UID."""
    if access.prometheus_datasource_uid is not None:
        return access.prometheus_datasource_uid
    try:
        payload = json.loads(http_request(access, "GET", grafana_url(access, "/api/datasources")))
    except json.JSONDecodeError as error:
        raise AccessError("Grafana datasource list is not valid JSON") from error
    return select_prometheus_datasource_uid(payload)


def select_prometheus_datasource_uid(payload: Any) -> str:
    """Select the default Prometheus datasource, otherwise the first returned."""
    values = payload.get("items") if isinstance(payload, dict) else payload
    require(isinstance(values, list), "Grafana datasource list is not an array")
    candidates = [
        item for item in values
        if isinstance(item, dict) and item.get("type") == "prometheus"
        and isinstance(item.get("uid"), str) and UID_RE.fullmatch(item["uid"]) is not None
    ]
    require(candidates, "no Prometheus datasource is configured")
    default = next((item for item in candidates if item.get("isDefault") in {True, 1, "true", "1"}), None)
    return (default or candidates[0])["uid"]


def prometheus_request_url(access: GrafanaAccess, request: dict[str, Any]) -> str:
    """Map an allowlisted read-only Prometheus operation to the datasource proxy."""
    require(set(request) == {"operation", "params"}, "request must contain only operation and params")
    operation = request["operation"]
    params = request["params"]
    require(isinstance(operation, str), "request operation must be a string")
    require(isinstance(params, dict), "request params must be an object")
    parameters = dict(params)
    encoded: list[tuple[str, str]] = []
    for name, value in parameters.items():
        require(isinstance(name, str) and PARAMETER_RE.fullmatch(name) is not None,
                "request parameter name is invalid")
        values = value if isinstance(value, list) else [value]
        require(1 <= len(values) <= 32 and all(isinstance(item, str) and len(item) <= 8192 for item in values),
                "request parameter value is invalid")
        encoded.extend((name, item) for item in values)

    paths = {
        "query": "/api/v1/query",
        "query_range": "/api/v1/query_range",
        "series": "/api/v1/series",
        "labels": "/api/v1/labels",
        "metadata": "/api/v1/metadata",
    }
    if operation in {"query", "query_range"}:
        require(isinstance(parameters.get("query"), str), "query operation requires a query parameter")
    if operation == "series":
        require("match[]" in parameters, "series operation requires a match[] parameter")
    if operation == "label_values":
        label = parameters.pop("label", None)
        require(isinstance(label, str) and LABEL_RE.fullmatch(label) is not None,
                "label_values operation requires a valid label parameter")
        path = f"/api/v1/label/{quote(label, safe='')}/values"
        encoded = [(name, value) for name, value in encoded if name != "label"]
    else:
        require(operation in paths, "Prometheus operation is not allowed")
        path = paths[operation]
    uid = prometheus_datasource_uid(access)
    proxy_path = f"/api/datasources/proxy/uid/{quote(uid, safe='')}{path}"
    query = urlencode(encoded)
    return grafana_url(access, proxy_path) + (f"?{query}" if query else "")


def read_json_file(path: Path, label: str) -> dict[str, Any]:
    """Read a bounded JSON object from a regular file."""
    require(path.is_file() and not path.is_symlink(), f"{label} file must be regular")
    try:
        raw = path.read_bytes()
        require(len(raw) <= 256 * 1024, f"{label} file is too large")
        value = json.loads(raw)
    except (OSError, json.JSONDecodeError) as error:
        raise AccessError(f"{label} file is not valid JSON") from error
    require(isinstance(value, dict), f"{label} file must contain a JSON object")
    return value


def write_response(path: Path, response: bytes) -> None:
    """Write a JSON response once so raw target data never reaches stdout."""
    try:
        json.loads(response)
    except json.JSONDecodeError as error:
        raise AccessError("Grafana response is not valid JSON") from error
    require(not path.exists(), "response file already exists")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as output:
            output.write(response)
    except OSError as error:
        raise AccessError("response file could not be written") from error
