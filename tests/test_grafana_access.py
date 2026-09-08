from __future__ import annotations

import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.grafana_access import (
    AccessError,
    GrafanaAccess,
    grafana_url,
    grafana_access_from_environment,
    prometheus_datasource_uid,
    prometheus_request_url,
    select_prometheus_datasource_uid,
)


class GrafanaAccessTest(unittest.TestCase):
    def setUp(self) -> None:
        self.access = GrafanaAccess(
            target="https://grafana.example.test/base/",
            client="curl",
            client_args=(),
            prometheus_datasource_uid="prometheus-default",
        )

    def test_grafana_url_preserves_fixed_query(self) -> None:
        self.assertEqual(
            "https://grafana.example.test/base/apis/dashboard?dryRun=All",
            grafana_url(self.access, "/apis/dashboard?dryRun=All"),
        )

    def test_prometheus_reader_uses_configured_datasource_and_allowed_operation(self) -> None:
        request = {"operation": "query", "params": {"query": "up", "time": "1"}}
        self.assertEqual(
            "https://grafana.example.test/base/api/datasources/proxy/uid/"
            "prometheus-default/api/v1/query?query=up&time=1",
            prometheus_request_url(self.access, request),
        )
        self.assertEqual({"operation": "query", "params": {"query": "up", "time": "1"}}, request)

    def test_prometheus_reader_rejects_arbitrary_operation(self) -> None:
        with self.assertRaisesRegex(AccessError, "not allowed"):
            prometheus_request_url(self.access, {"operation": "read", "params": {}})

    def test_configured_uid_does_not_need_datasource_discovery(self) -> None:
        self.assertEqual("prometheus-default", prometheus_datasource_uid(self.access))

    def test_datasource_selection_prefers_default_prometheus_and_then_first(self) -> None:
        self.assertEqual(
            "prometheus-default",
            select_prometheus_datasource_uid([
                {"uid": "other", "type": "loki", "isDefault": True},
                {"uid": "prometheus-first", "type": "prometheus", "isDefault": False},
                {"uid": "prometheus-default", "type": "prometheus", "isDefault": True},
            ]),
        )
        self.assertEqual(
            "prometheus-first",
            select_prometheus_datasource_uid([
                {"uid": "prometheus-first", "type": "prometheus", "isDefault": False},
                {"uid": "prometheus-second", "type": "prometheus", "isDefault": False},
            ]),
        )

    def test_access_loads_private_dotenv_and_environment_overrides_it(self) -> None:
        with TemporaryDirectory() as temporary:
            config = Path(temporary) / ".env"
            config.write_text(
                "GRAFANA_TARGET=https://grafana.example.test\n"
                "GRAFANA_HTTP_CLIENT=kcurl\n"
                "GRAFANA_HTTP_CLIENT_ARGS_JSON=[\"--netrc\"]\n",
                encoding="utf-8",
            )
            config.chmod(0o600)
            access = grafana_access_from_environment({}, env_path=config)
            self.assertEqual("https://grafana.example.test", access.target)
            self.assertEqual("kcurl", access.client)
            self.assertEqual(("--netrc",), access.client_args)

            overridden = grafana_access_from_environment(
                {"GRAFANA_HTTP_CLIENT": "curl"}, env_path=config,
            )
            self.assertEqual("curl", overridden.client)

    def test_access_rejects_an_insecure_dotenv(self) -> None:
        with TemporaryDirectory() as temporary:
            config = Path(temporary) / ".env"
            config.write_text("GRAFANA_TARGET=https://grafana.example.test\n", encoding="utf-8")
            config.chmod(0o644)
            with self.assertRaisesRegex(AccessError, "must not be group/world accessible"):
                grafana_access_from_environment({}, env_path=config)

    def test_set_workflow_env_writes_private_loadable_dotenv(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            scripts = root / "scripts"
            scripts.mkdir()
            for name in {"mkworkspace", "set_workflow_env", "grafana_access.py"}:
                shutil.copy2(repository / "scripts" / name, scripts / name)
            command = scripts / "set_workflow_env"
            command.chmod(0o755)
            created = subprocess.run(
                [sys.executable, str(scripts / "mkworkspace"), "demo"],
                capture_output=True,
                text=True,
                check=False,
                cwd=root,
            )
            workspace = root / "dashboards" / "demo" / "workspace"
            self.assertEqual(0, created.returncode, created.stdout + created.stderr)
            self.assertEqual(str(workspace), created.stdout.strip())
            result = subprocess.run(
                [sys.executable, str(command), "GRAFANA_TARGET", "https://grafana.example.test"],
                capture_output=True,
                text=True,
                check=False,
                cwd=workspace,
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            config = workspace / ".env"
            self.assertEqual(0o600, config.stat().st_mode & 0o777)
            self.assertEqual(
                "https://grafana.example.test",
                grafana_access_from_environment({}, env_path=config).target,
            )
