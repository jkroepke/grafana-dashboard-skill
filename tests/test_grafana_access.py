from __future__ import annotations

import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.grafana_access import (
    AccessError,
    GrafanaAccess,
    grafana_env,
    grafana_url,
    grafana_access_from_environment,
    prometheus_datasource_uid,
    prometheus_request_url,
    select_prometheus_datasource_uid,
    write_workflow_env,
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

    def test_grafana_access_defaults_to_curl(self) -> None:
        with TemporaryDirectory() as temporary:
            config = Path(temporary) / ".env"
            config.write_text("GRAFANA_TARGET=https://grafana.example.test\n", encoding="utf-8")
            config.chmod(0o600)
            self.assertEqual("curl", grafana_access_from_environment({}, env_path=config).client)

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
            self.assertRegex(
                (workspace / ".env").read_text(encoding="utf-8"),
                r"(?m)^WORKFLOW_RUN_ID=run-[0-9a-f]{16}$",
            )
            result = subprocess.run(
                [sys.executable, str(command), "GRAFANA_TARGET", "https://grafana.example.test"],
                capture_output=True,
                text=True,
                check=False,
                cwd=workspace,
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            result = subprocess.run(
                [sys.executable, str(command), "WORKFLOW_PUBLISH_REQUESTED", "true"],
                capture_output=True,
                text=True,
                check=False,
                cwd=workspace,
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            metrics_file = root / "metrics.txt"
            metrics_file.write_text("demo_metric 1\n", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(command), "METRICS_TARGET", str(metrics_file)],
                capture_output=True,
                text=True,
                check=False,
                cwd=workspace,
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            result = subprocess.run(
                [sys.executable, str(command), "METRICS_HTTP_CLIENT", ""],
                capture_output=True,
                text=True,
                check=False,
                cwd=workspace,
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            result = subprocess.run(
                [sys.executable, str(command), "GRAFANA_PROMETHEUS_DATASOURCE_UID", "manual"],
                capture_output=True,
                text=True,
                check=False,
                cwd=workspace,
            )
            self.assertEqual(2, result.returncode)
            self.assertIn("set_datasource", result.stderr)
            config = workspace / ".env"
            self.assertEqual(0o600, config.stat().st_mode & 0o777)
            self.assertIn("WORKFLOW_PUBLISH_REQUESTED=true", config.read_text(encoding="utf-8"))
            self.assertEqual(
                "https://grafana.example.test",
                grafana_access_from_environment({}, env_path=config).target,
            )

    def test_mkworkspace_starts_fresh_unless_resume_is_explicit(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            scripts = root / "scripts"
            scripts.mkdir()
            for name in {"mkworkspace", "workflow", "grafana_access.py"}:
                shutil.copy2(repository / "scripts" / name, scripts / name)
            command = [sys.executable, str(scripts / "mkworkspace"), "demo"]
            first = subprocess.run(command, capture_output=True, text=True, check=False, cwd=root)
            self.assertEqual(0, first.returncode, first.stdout + first.stderr)
            config = root / "dashboards" / "demo" / "workspace" / ".env"
            initial = grafana_env(config)["WORKFLOW_RUN_ID"]
            self.assertEqual(str(scripts / "workflow"), (config.parent / "workflow").readlink().as_posix())
            write_workflow_env(config, {"WORKFLOW_RUN_ID": initial, "GRAFANA_TARGET": "https://stale.example.test"})

            fresh = subprocess.run(command, capture_output=True, text=True, check=False, cwd=root)
            self.assertEqual(0, fresh.returncode, fresh.stdout + fresh.stderr)
            current = grafana_env(config)["WORKFLOW_RUN_ID"]
            self.assertNotEqual(initial, current)
            self.assertNotIn("GRAFANA_TARGET", grafana_env(config))

            resumed = subprocess.run(command + ["--resume"], capture_output=True, text=True, check=False, cwd=root)
            self.assertEqual(0, resumed.returncode, resumed.stdout + resumed.stderr)
            self.assertEqual(current, grafana_env(config)["WORKFLOW_RUN_ID"])

    def test_metrics_reader_streams_a_local_target_without_client(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        with TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "dashboards" / "demo" / "workspace"
            workspace.mkdir(parents=True)
            metrics_file = Path(temporary) / "metrics.txt"
            metrics_file.write_bytes(b"# TYPE demo_metric gauge\ndemo_metric 1\n")
            (workspace / ".env").write_text(
                f"METRICS_TARGET={metrics_file}\nMETRICS_HTTP_CLIENT=\n",
                encoding="utf-8",
            )
            (workspace / ".env").chmod(0o600)
            result = subprocess.run(
                [sys.executable, str(repository / "scripts" / "metrics_reader.py")],
                capture_output=True,
                check=False,
                cwd=workspace,
            )
            self.assertEqual(0, result.returncode, result.stderr.decode())
            self.assertEqual(metrics_file.read_bytes(), result.stdout)

    def test_metrics_reader_defaults_to_curl_for_http_target(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "dashboards" / "demo" / "workspace"
            workspace.mkdir(parents=True)
            curl = root / "curl"
            curl.write_text("#!/bin/sh\nprintf 'demo_metric 1\\n'\n", encoding="utf-8")
            curl.chmod(0o755)
            (workspace / ".env").write_text(
                "METRICS_TARGET=https://metrics.example.test/metrics\n",
                encoding="utf-8",
            )
            (workspace / ".env").chmod(0o600)
            result = subprocess.run(
                [sys.executable, str(repository / "scripts" / "metrics_reader.py")],
                capture_output=True,
                check=False,
                cwd=workspace,
                env={**os.environ, "PATH": f"{root}:{os.environ['PATH']}"},
            )
            self.assertEqual(0, result.returncode, result.stderr.decode())
            self.assertEqual(b"demo_metric 1\n", result.stdout)

    def test_set_datasource_persists_the_default_prometheus_uid(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "dashboards" / "demo" / "workspace"
            workspace.mkdir(parents=True)
            client = root / "client"
            client.write_text(
                "#!/bin/sh\n"
                "while [ \"$#\" -gt 0 ]; do\n"
                "  case \"$1\" in --output) output=$2; shift 2;; *) url=$1; shift;; esac\n"
                "done\n"
                "test \"$url\" = https://grafana.example.test/api/datasources || exit 1\n"
                "printf '%s' '[{\"uid\":\"first\",\"type\":\"prometheus\"},{\"uid\":\"default\",\"type\":\"prometheus\",\"isDefault\":true}]' > \"$output\"\n"
                "printf 200\n",
                encoding="utf-8",
            )
            client.chmod(0o755)
            config = workspace / ".env"
            config.write_text(
                "GRAFANA_TARGET=https://grafana.example.test\n"
                f"GRAFANA_HTTP_CLIENT={client}\n"
                "GRAFANA_HTTP_CLIENT_ARGS_JSON=[]\n",
                encoding="utf-8",
            )
            config.chmod(0o600)
            result = subprocess.run(
                [sys.executable, str(repository / "scripts" / "set_datasource")],
                capture_output=True,
                text=True,
                check=False,
                cwd=workspace,
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("GRAFANA_PROMETHEUS_DATASOURCE_UID=default", config.read_text(encoding="utf-8"))
