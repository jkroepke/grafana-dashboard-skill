from __future__ import annotations

import unittest

from scripts.grafana_access import (
    AccessError,
    GrafanaAccess,
    grafana_url,
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
