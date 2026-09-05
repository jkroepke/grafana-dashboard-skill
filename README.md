# Grafana Dashboard Skill

Local agent skill for creating or updating Grafonnet dashboards for Kubernetes applications from Prometheus/OpenMetrics metrics.

The workflow is designed for an air-gapped agent with a limited context window. Give it file paths and local read-only datasource access instead of pasting large metric dumps or query responses.

## Start a task

Use a focused prompt:

```text
Use the grafana-dashboard skill.

Create or update the Grafana dashboard for <application>.
Metrics dump: <path>
Kubernetes manifests: <path or none>
Existing dashboard: <path or none>
Read-only Grafana/Prometheus access: <local instructions or none>

Do not publish the dashboard.
```

Only include paths and constraints relevant to the application. The coordinator delegates metric analysis, difficult PromQL, panel selection, and final review to the repository subagents when the task is substantial.

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

New dashboards default to Dashboard Schema V2 when supported by the pinned local Grafana/Grafonnet dependencies.
