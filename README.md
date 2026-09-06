# Grafana Dashboard Skill

Local agent skill for creating, updating, validating, and optionally publishing Grafonnet dashboards for Kubernetes applications from Prometheus/OpenMetrics metrics.

The workflow is designed for an air-gapped agent with a limited context window. Give it file paths and local datasource/API access instead of pasting large metric dumps or query responses.

## Start a task

Use a focused prompt:

```text
Use the grafana-dashboard skill.

Create or update the Grafana dashboard for <application>.
Metrics dump: <path>
Kubernetes manifests: <path or none>
Existing dashboard: <path or none>
Grafana/Prometheus access: <opaque local access instructions or none>
Publish: <yes|no>
Folder UID: <uid or none>
```

For `Publish: yes`, provide writable Grafana dashboard API access. Prometheus datasource access may remain read-only.

Do not paste target endpoints, host/domain details, credentials, or unrelated resource identifiers into the task prompt. Use an opaque local wrapper/environment reference. Visible command/output redaction is defined in `knowledge/security/output-redaction.md`.

The Grafana Dashboard resource namespace is always `default`. Do not provide or derive another API namespace.

The coordinator builds and validates the dashboard first, runs an independent review, and only then publishes it.

## Dashboard V2 publishing

For Dashboard Schema V2, the agent must use the Dashboard resource API instead of the legacy dashboard endpoint.

Use the target Grafana Swagger/OpenAPI schema through the configured opaque target access as the API contract source of truth. Do not print or copy the resolved Swagger endpoint into visible output.

The target Grafana Swagger wins if it exposes a different supported API version. The Dashboard resource namespace remains `default`.

Detailed publish rules are in `knowledge/grafana/publishing-v2.md`.

## Target environment contract

Application series stored in Prometheus use:

```text
kubernetes_namespace
kubernetes_pod_name
```

The raw `/metrics` exposition does not need to contain these labels; the scrape pipeline may attach them.

Every generated dashboard uses:

- `datasource`: Prometheus datasource, single value
- `namespace`: single value
- `pod`: multi value with bounded All behavior

The dashboard variable named `namespace` is unrelated to the Grafana Dashboard resource API namespace, which is always `default`.

New dashboards default to Dashboard Schema V2 when supported by the pinned local Grafana/Grafonnet dependencies.
