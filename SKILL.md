---
name: grafana-dashboard
description: Create, update, validate, and optionally publish Grafonnet dashboards for Kubernetes applications and APIs from Prometheus or OpenMetrics metrics. Use application metrics first, add Kubernetes context where useful, and default new dashboards to Dashboard Schema V2.
---

# Grafana dashboards for Kubernetes applications

Create or update Grafonnet dashboards. Keep application behavior prominent. Add Kubernetes signals only when they explain workload health, capacity, or resource use.

## Environment

This workflow runs air-gapped with a 256k context limit.

- Do not depend on internet access during normal runtime.
- Use repository files, supplied metrics/manifests, pinned local dependencies, configured Grafana/Prometheus access, and `knowledge/`.
- Treat unknown facts as unknown. Do not invent metrics, labels, workload names, recording rules, Grafonnet methods, schema fields, API routes, or credentials.
- Prefer file paths and targeted excerpts over copying large inputs into agent contexts.
- Leave raw metrics dumps and large query responses on disk.

## Runtime compatibility

Canonical subagent definitions live in `agents/` and are exposed by the repository symlinks for OpenCode, Kilo, Pi, and shared agent discovery.

Invoke specialists by agent ID:

- `application-metrics`
- `kubernetes-metrics`
- `promql-expert`
- `panel-expert`
- `dashboard-reviewer`

The repository exposes the skill through `.agents/skills/grafana-dashboard`. Keep the runtime symlink layout intact.

When Pi uses a subagent extension with an agent-scope option, enable project agents (`project` or `both`).

Do not duplicate agent definitions for individual runtimes.

## Scope

- Create or update dashboard source.
- Publish/write a dashboard only when the user explicitly requests it and writable Grafana dashboard API access is available.
- Read-only datasource access may be used for discovery and validation.
- Default new dashboards to Dashboard Schema V2.
- Preserve the schema of an existing dashboard unless migration is requested.
- Preserve existing dashboard identity, unrelated panels, repository helpers, and dependency pins.
- Use the repository dashboard location, or `dashboards/<service>.jsonnet` when none exists.
- The coordinator owns all final dashboard and shared-helper edits and all publish operations.

Do not publish before rendering, validation, and independent review are complete.

## Establish the shared contract

Before delegation, determine from local evidence:

- application/workload identity
- relevant containers and sidecars
- Grafana version and dashboard schema
- Grafonnet revision
- cluster scope
- scrape intervals when available
- available metric sources
- fixed selectors required to identify the application
- configured datasource access method
- whether publication is requested
- when publication is requested: Grafana base URL, writable authentication method, dashboard namespace, existing dashboard name/UID when applicable, and folder UID when applicable

Use evidence in this order:

1. local source and configuration
2. supplied metric metadata
3. verified live datasource/API data
4. local `knowledge/` contracts

A single exposition dump proves observed samples and exporter/instrumentation labels only. It does not prove historical behavior, every possible label value, or labels attached by the scrape pipeline.

Treat exposition labels and stored scrape labels separately. In this target environment, `kubernetes_namespace` and `kubernetes_pod_name` are valid stored application labels and may be attached by the scrape pipeline. Their absence from a raw `/metrics` dump does not invalidate the stored-series selector contract.

## Required dashboard variables

Every dashboard has these variables in dependency order:

| Name | Source | Selection |
| --- | --- | --- |
| `datasource` | Prometheus datasource | single, no All |
| `namespace` | application-scoped `kubernetes_namespace` | single, no All |
| `pod` | application-scoped `kubernetes_pod_name` | multi, All enabled with empty custom All value |

Use `$datasource` for every Prometheus target, variable query, and annotation. Never embed a discovered datasource UID.

Application metrics use the target-environment stored labels:

```promql
<metric>{kubernetes_namespace="$namespace",kubernetes_pod_name=~"${pod:regex}"}
```

Kubernetes support metrics normally use native workload labels:

```promql
<metric>{namespace="$namespace",pod=~"${pod:regex}"}
```

Apply verified fixed application and cluster selectors consistently. Do not substitute an unbounded `.*` for the pod population unless every affected query independently enforces application scope.

Read `knowledge/grafana/variables.md` when implementing or reviewing variables.

## Specialist workflow

Use dedicated agents for substantial dashboard creation or updates when isolated subagent contexts are available. Handle small focused edits directly.

Do not create recursive subagent trees. The coordinator performs all specialist dispatch.

### 1. Application analysis

Delegate to `application-metrics`.

Give it only:

- application metric dump path
- relevant metric inventory or selected families
- shared contract
- read-only query access instructions when available

It returns selected operational questions, straightforward scoped PromQL, units, retained labels, validation results, unresolved semantics, annotation-source candidates, and isolated PromQL consultation requests when needed.

### 2. Kubernetes analysis

Delegate to `kubernetes-metrics`.

Give it only:

- workload manifests or verified workload identity
- relevant container set
- shared contract
- read-only query access instructions when available

It returns health/resource questions, straightforward scoped PromQL, matching keys, container populations, validation results, availability limits, optional annotation-source candidates, and isolated PromQL consultation requests when needed.

Run application and Kubernetes analysis concurrently when the runtime can do so without duplicating large inputs.

### 3. Difficult PromQL

For each isolated consultation request, invoke `promql-expert` with only the affected operational question, metric metadata, selectors, scrape timing, candidate expression, and relevant evidence.

Typical triggers:

- sparse or late-created counters
- resets or staleness
- zero versus absent
- histogram calculations
- joins or vector matching
- KSM ownership joins
- subqueries or offset semantics
- cardinality or query-cost concerns

Do not route straightforward queries through the PromQL expert when their semantics are already established.

Do not integrate a result marked `REJECT` or `NEEDS_EVIDENCE`. Resolve the missing evidence or omit the panel/query.

### 4. Panel plan

After selecting queries, batch operational questions and result shapes to `panel-expert` for a substantial new dashboard or when visualization choice is non-obvious.

The panel expert recommends visualization, query mode, unit, legend, sizing, and placement. It does not modify PromQL or dashboard files.

### 5. Integration

The coordinator integrates only selected queries and builds the dashboard using pinned local Grafonnet APIs.

Read local Grafana knowledge only as needed:

- `knowledge/grafana/panel-selection.md`
- `knowledge/grafana/layout-v2.md`
- `knowledge/grafana/variables.md`
- `knowledge/grafana/annotations.md`

When a verified process/container start-timestamp metric exists, read `knowledge/grafana/annotations.md`. Add an annotation only when a sparse event-like query validates without misleading duplicates or flooding; never query a continuously scraped timestamp gauge directly as an annotation.

### 6. Independent review

After rendering, delegate to `dashboard-reviewer`.

Give the reviewer:

- final Jsonnet source
- rendered JSON
- shared contract
- pinned Grafana/Grafonnet versions
- relevant raw fixture paths
- read-only datasource access instructions when available

Do not give it analyst conclusions or expected findings. A worker must not approve its own output.

Fix confirmed findings in the coordinator context and render/review again when the fix can affect dashboard semantics.

### 7. Publish when requested

Publish only after the dashboard has passed the applicable local validation and independent review.

Read:

- `knowledge/grafana/publishing-v2.md`

For Dashboard Schema V2, use the Grafana Dashboard resource API. Do not use the legacy `/api/dashboards/db` endpoint and do not convert the dashboard to classic JSON merely to publish it.

The API contract source of truth is the target Grafana Swagger:

```text
<GRAFANA_URL>/swagger?api=dashboard.grafana.app-v2
```

When internet access exists, the public reference is:

```text
https://play.grafana.org/swagger?api=dashboard.grafana.app-v2
```

The target Grafana Swagger wins. If the target advertises `v2beta1`, `v2alpha1`, or another supported structured dashboard version instead of stable `v2`, use that target-advertised API and schema. Never guess an API version.

For stable V2 the resource routes are normally:

```text
POST /apis/dashboard.grafana.app/v2/namespaces/<namespace>/dashboards
GET  /apis/dashboard.grafana.app/v2/namespaces/<namespace>/dashboards/<name>
PUT  /apis/dashboard.grafana.app/v2/namespaces/<namespace>/dashboards/<name>
```

Confirm methods and request bodies from Swagger before writing.

- New dashboard: use the collection create operation.
- Existing dashboard: GET it first, preserve identity/folder placement unless intentionally changed, then use the documented replace/update operation.
- Use the rendered Schema V2 `spec`; do not blindly POST a classic DTO or arbitrary Jsonnet output envelope.
- Never create a duplicate dashboard because an update failed.
- Never expose credentials or authorization headers in output.

After writing, GET the resource again through the same API version and verify the returned dashboard name, title, required variables, and expected V2 layout. A write response alone is not sufficient publication verification.

## Context discipline

- Do not give subagents the complete conversation.
- Do not give subagents the complete `SKILL.md`; their registered agent definition is their role contract.
- Give each subagent only shared-contract fields and local files needed for its task.
- Parse large metric dumps once, then retrieve selected families with metadata and representative label sets.
- Do not paste complete Grafana frames or API responses into the coordinator context.
- Store large requests/responses in temporary files and return a path when targeted inspection is needed.
- Keep rejected alternatives out of the coordinator context unless they expose a correctness issue.
- Avoid concurrent edits. Analysts and reviewers propose; the coordinator writes final source.
- Treat 256k as a hard ceiling, not a target.

## Dashboard content priorities

Choose panels by operational question, not by metric count:

1. traffic/work rate, failures, duration, application-specific outcomes
2. saturation, concurrency, queues, dependency behavior
3. readiness, resource usage, restarts, configured capacity
4. runtime, database, network, or filesystem details only when supported by useful metrics

Database panels are optional. Do not invent HTTP signals for workers or batch applications.

## PromQL requirements

- Apply `rate()` or `increase()` to individual counters before aggregation.
- Use `$__rate_interval` for counter rates.
- Use `$__range` for selected-period totals when that is the intended question.
- `rate()` and `increase()` need enough samples to calculate a change; a newly observed series with only one sample produces no useful increase.
- Do not silently convert missing data to zero.
- Distinguish absent instrumentation, failed scraping, zero activity, stale series, and missing configuration.
- Do not invent health thresholds.
- Escalate non-trivial semantics to `promql-expert` with only the relevant metric families and evidence.

## Kubernetes requirements

Read `knowledge/kubernetes/metrics.md` when Kubernetes context is used.

- Keep application metric labels separate from native KSM/cAdvisor labels.
- Exclude cAdvisor `container=""` and `container="POD"` for container resource calculations.
- Match identical container populations before comparing usage with requests or limits.
- Do not interpret missing or zero limits as numeric capacity.
- Do not guess workload names from pod-name regexes when owner relationships are available.
- Prefer verified scheduler pod resource metrics for pod-level scheduling capacity when available; retain KSM container metrics for per-container comparisons.

## Grafana and Grafonnet requirements

- Prefer built-in visualizations.
- For V2, use layout kinds supported by the pinned schema, such as `AutoGridLayout`, `GridLayout`, `RowsLayout`, and `TabsLayout`.
- Prefer `AutoGridLayout` for similarly sized panels and `GridLayout` only for deliberate size/position differences.
- Use tabs or rows only when each section contains enough useful content.
- Inspect pinned generated Grafonnet methods when uncertain; do not guess method or schema shapes.
- Preserve dependency pins.
- Keep code-managed dashboards non-editable unless repository policy explicitly requires UI editing.

## Local validation

Prefer repository build commands. When applicable, validate with installed local tools:

```bash
jsonnetfmt -i <dashboard.jsonnet>
jsonnet -J vendor <dashboard.jsonnet> > /tmp/dashboard.json
jq empty /tmp/dashboard.json
dashboard-linter lint --strict --config <lint-config> /tmp/dashboard.json
```

Use the repository's actual paths and commands when they differ. `jq empty` checks JSON syntax only, not Grafana schema correctness.

When datasource access is available, test representative application, Kubernetes, variable, and annotation queries with explicit values replacing dashboard variables and macros. HTTP success alone is not a pass: inspect datasource errors, warnings, series count, label keys, duplicate series, representative values, and empty-result semantics.

For Prometheus annotations, verify that the query returns only event-like points. Every returned datapoint becomes a marker, so continuous timestamp gauges or overlapping change windows can flood or duplicate annotations.

Test one pod, multiple pods, and All where supported.

If live datasource access is unavailable, mark live-query and annotation validation `UNVERIFIED`; never infer a pass from static inspection alone.

## Completion

Report only:

- source paths changed
- schema
- major panel groups added or changed
- important omitted signals and why
- render/schema/lint status
- live-query validation status
- annotation validation status when applicable
- publish status when requested: API version, namespace, dashboard resource name/UID, and verification result
