---
name: grafana-dashboard-from-metrics
description: Create or update local Grafonnet dashboards for Kubernetes applications and APIs from Prometheus or OpenMetrics exposition dumps. Use application metrics first, add Kubernetes health and resource context where useful, and default to Dashboard Schema V2.
---

# Grafana dashboards for Kubernetes applications

Create or update local Grafonnet dashboards. Keep application behavior prominent. Add Kubernetes signals only when they explain workload health, capacity, or resource use.

## Environment

This workflow runs air-gapped with a 256k context limit.

- Do not use internet access or depend on external documentation.
- Use repository files, supplied metrics/manifests, pinned local dependencies, configured read-only Grafana/Prometheus access, and `knowledge/`.
- Treat unknown facts as unknown. Do not invent metrics, labels, workload names, recording rules, Grafonnet methods, or schema fields.
- Prefer file paths and targeted excerpts over copying large inputs into agent contexts.
- Leave raw metrics dumps and large query responses on disk.

## Scope

- Create or update dashboard source only. Do not publish, import, provision, or write dashboards through Grafana APIs.
- Read-only datasource access may be used for discovery and validation.
- Default new dashboards to Dashboard Schema V2.
- Preserve the schema of an existing dashboard unless migration is requested.
- Preserve existing dashboard identity, unrelated panels, repository helpers, and dependency pins.
- Use the repository dashboard location, or `dashboards/<service>.jsonnet` when none exists.
- The coordinator owns all final dashboard and shared-helper edits.

## Establish the shared contract

Before delegation, determine from local evidence:

- application/workload identity
- relevant containers and sidecars
- Grafana version and schema
- Grafonnet revision
- cluster scope
- scrape intervals when available
- available metric sources
- fixed selectors required to identify the application
- configured read-only datasource access method when available

Use evidence in this order:

1. local source and configuration
2. supplied metric metadata
3. verified live datasource data
4. local `knowledge/` contracts

A single exposition dump proves observed samples only. It does not prove historical behavior or every possible label value.

## Required dashboard variables

Every dashboard has these variables in dependency order:

| Name | Source | Selection |
| --- | --- | --- |
| `datasource` | Prometheus datasource | single, no All |
| `namespace` | application-scoped `kubernetes_namespace` | single, no All |
| `pod` | application-scoped `kubernetes_pod_name` | multi, All enabled with empty custom All value |

Use `$datasource` for every Prometheus target, variable query, and annotation. Never embed a discovered datasource UID.

Application metrics use the scrape-time labels:

```promql
<metric>{kubernetes_namespace="$namespace",kubernetes_pod_name=~"${pod:regex}"}
```

Kubernetes support metrics normally use native workload labels:

```promql
<metric>{namespace="$namespace",pod=~"${pod:regex}"}
```

Apply verified fixed application and cluster selectors consistently. Do not substitute an unbounded `.*` for the pod population unless every affected query independently enforces application scope.

For full variable rules, read `knowledge/grafana/variables.md` only when implementing or reviewing variables.

## Specialist workflow

Use dedicated agents for substantial dashboard creation or updates when isolated sub-agent contexts are available. Handle small focused edits directly.

### 1. Application analysis

Delegate to `agents/application-metrics.md`.

Give it only:

- application metric dump path
- relevant metric inventory or selected families
- shared contract
- read-only query access instructions when available

It returns selected operational questions, scoped PromQL, units, retained labels, live-validation results, and unresolved semantics.

### 2. Kubernetes analysis

Delegate to `agents/kubernetes-metrics.md`.

Give it only:

- workload manifests or verified workload identity
- relevant container set
- shared contract
- read-only query access instructions when available

It returns health/resource questions, scoped PromQL, matching keys, container populations, live-validation results, and availability limits.

Run application and Kubernetes analysis concurrently when the runtime can do so without duplicating large inputs.

### 3. Difficult PromQL

Use `agents/promql-expert.md` on demand for non-trivial PromQL semantics. Typical triggers:

- sparse or late-created counters
- resets or staleness
- zero versus absent
- histogram calculations
- joins or vector matching
- KSM ownership joins
- subqueries or offset semantics
- cardinality or query-cost concerns

Do not route straightforward queries through the PromQL expert when their semantics are already established.

### 4. Panel plan

After selecting queries, batch the selected operational questions and query result shapes to `agents/panel-expert.md` for a substantial new dashboard or when visualization choice is non-obvious.

The panel expert recommends visualization, query mode, unit, legend, sizing, and placement. It does not modify PromQL or dashboard files.

### 5. Integration

The coordinator integrates only selected queries and builds the dashboard using pinned local Grafonnet APIs.

Read local Grafana knowledge only as needed:

- `knowledge/grafana/panel-selection.md`
- `knowledge/grafana/layout-v2.md`
- `knowledge/grafana/variables.md`
- `knowledge/grafana/annotations.md`

### 6. Independent review

After rendering, delegate to `agents/dashboard-reviewer.md`.

Give the reviewer:

- final Jsonnet source
- rendered JSON
- shared contract
- pinned Grafana/Grafonnet versions
- relevant raw fixtures by path
- read-only datasource access instructions when available

Do not give it analyst conclusions or expected findings. A worker must not approve its own output.

Fix confirmed findings in the coordinator context.

## Context discipline

- Do not give sub-agents the complete conversation.
- Do not give sub-agents the complete `SKILL.md` unless required by the runtime. Give the agent definition, shared contract, and only relevant knowledge files.
- Parse large metric dumps once, then retrieve selected families with metadata and representative label sets.
- Do not paste complete Grafana frames or API responses into the coordinator context.
- Store large requests/responses in worker-owned temporary files and return a path when targeted inspection is needed.
- Return compact findings. Keep rejected alternatives out of the coordinator context unless they expose a correctness issue.
- Avoid recursive agent trees. `promql-expert` is an on-demand consultant, not a new orchestration layer.
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
- Do not silently convert missing data to zero.
- Distinguish absent instrumentation, failed scraping, zero activity, stale series, and missing configuration.
- Do not invent health thresholds.
- Escalate non-trivial semantics to `agents/promql-expert.md` with only the relevant metric families and evidence.

## Kubernetes requirements

Read `knowledge/kubernetes/metrics.md` when Kubernetes context is used.

- Keep application metric labels separate from native KSM/cAdvisor labels.
- Exclude cAdvisor `container=""` and `container="POD"` for container resource calculations.
- Match identical container populations before comparing usage with requests or limits.
- Do not interpret missing or zero limits as numeric capacity.
- Do not guess workload names from pod-name regexes when owner relationships are available.

## Grafana and Grafonnet requirements

- Prefer built-in visualizations.
- For V2, prefer AutoGrid for similarly sized panels and custom grid only for deliberate size differences.
- Use tabs only when each tab contains enough useful content.
- Inspect pinned generated Grafonnet methods when uncertain; do not guess method or schema shapes.
- Preserve dependency pins.
- Keep code-managed dashboards non-editable unless the repository explicitly requires UI editing.

## Local validation

Prefer repository build commands. When applicable, validate with installed local tools:

```bash
jsonnetfmt -i dashboards/application.jsonnet
jsonnet -J vendor dashboards/application.jsonnet > /tmp/application-dashboard.json
jq empty /tmp/application-dashboard.json
dashboard-linter lint --strict --config dashboards/.lint /tmp/application-dashboard.json
```

`jq empty` checks JSON syntax only, not Grafana schema correctness.

When read-only datasource access is available, test representative application, Kubernetes, variable, and annotation queries with explicit values replacing dashboard variables and macros. HTTP success alone is not a pass: inspect datasource errors, warnings, series count, label keys, duplicate series, representative values, and empty-result semantics.

Test one pod, multiple pods, and All where supported.

## Completion

Report only:

- source paths changed
- schema
- major panel groups added or changed
- important omitted signals and why
- render/schema/lint status
- live-query validation status
- annotation validation status when applicable
