# Grafana Dashboard Skill

Local agent skill for creating, updating, validating, and optionally publishing Grafonnet dashboards for Kubernetes applications from Prometheus/OpenMetrics metrics.

The workflow is designed for air-gapped DeepSeek V3.7 agents with a 256k context window running through OpenCode or Pi. It uses fresh specialist contexts and bounded file-backed artifacts. Give it file paths and local datasource/API access instead of pasting large metric dumps or query responses.

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
Folder placement: <opaque configured reference or none>
```

For `Publish: yes`, provide writable Grafana dashboard API access. Prometheus datasource access may remain read-only.

Do not paste target endpoints, host/domain details, credentials, or unrelated resource identifiers into the task prompt. Use an opaque local wrapper/environment reference. Visible command/output redaction is defined in `knowledge/security/output-redaction.md`.

For a Dashboard V2 target that is reachable only through a local command,
provide the shell-free opaque command that emits
`/openapi/v3/apis/dashboard.grafana.app/v2` to stdout. It must already know the
target and authentication; the coordinator runs it once, stores its output
privately, and never replaces it with a direct URL request.

The Grafana Dashboard resource namespace is always `default`. Do not provide or derive another API namespace.

The mandatory pipeline is:

```text
metric inventories -> metrics review -> dashboard architecture
  -> PromQL build -> PromQL review
  -> staged dashboard build -> dashboard review
  -> mechanical promotion -> optional publisher
```

`promql-builder` exclusively owns all Prometheus panel, variable, and annotation query text. `dashboard-builder` writes only a staged candidate. The coordinator routes artifact paths and digests, then promotes the exact approved candidate without reconstructing it in the coordinator context. A fresh `dashboard-publisher` performs the optional API write and readback verification.

## Runtime setup

The project has one primary agent, `coordinator`, and nine specialist
subagents. The coordinator may create the run contract and route artifacts,
but may not gather metric semantics, author queries, build, review, or publish
in place of a specialist.

### OpenCode

The committed `opencode.json` selects `coordinator` as the project default
agent. The existing `.opencode/agents` symlink exposes the coordinator and all
specialists. Reload or start a new OpenCode session from the repository so the
project configuration is applied.

### Pi

Install and reload the persistent main-agent mode:

```bash
pi install npm:@pi-kaush/pi-agent-mode
```

Start Pi in this repository, then activate the root role before giving the
dashboard task:

```text
/agent coordinator
```

`@pi-kaush/pi-agent-mode` selects the coordinator and keeps that role active
for the session. It does not provide a child-agent tool. Install and enable a
compatible Pi subagent extension as well; configure it to discover project
agents with `agentScope: "project"` or `"both"`. The repository's
`.pi/agents` symlink then supplies the same nine specialist definitions used by
OpenCode. If that tool or a required specialist is unavailable, the
coordinator must stop rather than gather or implement the missing stage.

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
