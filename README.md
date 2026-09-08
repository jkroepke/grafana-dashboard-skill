# Grafana Dashboard Skill

Local agent skill for creating, updating, validating, and optionally publishing Dashboard Schema V2 Grafonnet dashboards for Kubernetes applications from Prometheus/OpenMetrics metrics. It requires Grafana v13 or later.

## Hard compatibility boundary

This skill and its workflow support only Dashboard Schema V2 resources on Grafana v13+.

- Provide a verified Grafana version in `v<major>[.<minor>[.<patch>]]` form; versions below v13 are rejected.
- The target must advertise the stable Dashboard V2 resource API.
- Existing sources must render as Dashboard Schema V2 resources. Classic dashboard JSON, classic-to-V2 migrations, and the legacy dashboard API are out of scope.

The workflow is designed for air-gapped DeepSeek V3.7 agents with a 256k context window running through OpenCode or Pi. It uses fresh specialist contexts and bounded file-backed artifacts. Give it file paths and local datasource/API access instead of pasting large metric dumps or query responses.

## Start a task

Use a focused prompt:

```text
Use the grafana-dashboard skill.

Create or update the Grafana dashboard for <application>.
Metrics dump: <path>
Kubernetes manifests: <path or none>
Existing dashboard: <path or none>
Grafana access bootstrap: <target and client details>
Publish: <yes|no>
Folder placement: <configured reference or none>
```

For `Publish: yes`, provide writable Grafana dashboard API access. Prometheus datasource access may remain read-only.

Provide target and client details in the task. The coordinator writes them to
`dashboards/<project-name>/workspace/.env` with `scripts/set_workflow_env`,
then runs `scripts/grafana_version.py` exactly once. The coordinator extracts the
Grafana version only from `gitTreeState`, which must be `grafana v<version>`;
it ignores the Kubernetes API-style `major` and `minor` fields and `gitVersion`.

## Grafana capabilities

The coordinator first runs `scripts/mkworkspace <project-name>` and uses its
returned absolute workspace directory as the current working directory. It then configures
`dashboards/<project-name>/workspace/.env` through
`scripts/set_workflow_env <name> <value>`. It may set `GRAFANA_TARGET`,
`GRAFANA_HTTP_CLIENT`, `GRAFANA_HTTP_CLIENT_ARGS_JSON`, and
`GRAFANA_PROMETHEUS_DATASOURCE_UID`; all wrappers load the file automatically.
Do not shell-source or print it. The provided wrappers keep the target,
credentials, proxy path, and datasource UID out of later agent arguments:

```text
scripts/grafana_version.py
scripts/grafana_prometheus_datasource.py
scripts/prometheus_reader.py <request.json> <response.json>
scripts/grafana_dry_run.py <resource.json> <response.json>
```

`prometheus_reader.py` resolves the configured Prometheus datasource internally
(default first, otherwise the first returned) and accepts only the read-only
`query`, `query_range`, `series`, `labels`, `label_values`, and `metadata`
operations. Request and response files remain in the assigned workspace.
`grafana_prometheus_datasource.py` is a trusted bootstrap helper; do not hand
it to agents as an access capability.

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

The agent must use the Dashboard resource API instead of the legacy dashboard endpoint.

Do not fetch or inspect a target OpenAPI specification. The V2 workflow uses
the pinned/local V2 contract and the configured API wrapper. The Dashboard
resource namespace remains `default`.

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

Every dashboard handled by this workflow is Dashboard Schema V2; classic dashboards are rejected rather than preserved or migrated.
