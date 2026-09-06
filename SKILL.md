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

## Confidentiality

**MUST read `knowledge/security/output-redaction.md` before any target-system access, specialist handoff containing target context, or visible completion output.**

Sensitive target information may be used internally when required to perform the task, but MUST NOT appear in visible agent text, subagent output, visible shell commands, command previews, diagnostic ledgers, review findings, or completion summaries.

Treat target connection details, host/domain information, organization/customer identifiers, cluster/environment names, dashboard/resource identifiers, unrelated discovered resource IDs, local paths revealing target identity, and all authentication/session material as sensitive.

Hard rules:

- Never place a literal target endpoint in a visible command. Use an already configured opaque wrapper/environment reference whose value is not echoed.
- Never assign a sensitive endpoint/identifier value in the same visible command that uses it.
- Never print resolved connection variables, credential files, tokens, cookies, authorization headers, or netrc contents.
- Never repeat sensitive literals merely because they appeared in input, previous output, an API response, or an error body.
- Keep raw target responses in local scratch files; surface only sanitized fields/evidence.
- Do not print unrelated dashboard/resource IDs while probing target examples.
- Use placeholders such as `<TARGET>`, `<DASHBOARD_ID>`, `<RESOURCE_ID>`, `<CLUSTER>`, `<ENVIRONMENT>`, and `<APPLICATION>` in visible prose/commands when a role label is needed.
- A technically correct dashboard that leaks target information in the visible transcript is a failed workflow.

## Execution discipline

Act on a decided diagnostic step instead of narrating it repeatedly.

- Do not emit repeated self-dialogue such as `Let me ...`, `Wait ...`, `Actually ...`, `I will ...`, or multiple restatements of the same next command.
- Never state the same intended action twice without new tool/command output between the statements. Execute it; if execution is impossible, report the concrete blocker.
- One diagnostic step is: hypothesis -> one changed candidate -> one action -> one result -> one recorded fact.
- Do not rerun an identical request against an identical target operation unless deterministic reproduction is explicitly needed.
- Preserve proven PASS/FAIL facts; do not reopen an unchanged hypothesis without new interaction evidence.
- For Dashboard V2 target-validation failures requiring more than one probe, MUST read `knowledge/grafana/diagnostic-execution.md`. Use its diagnostic ledger and six-probe isolation budget.
- Prefer direct repository commands and `jq` structural slicing over repeatedly generating throwaway helper scripts.

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
- Dashboard Schema V2 server-side dry-run validation is not publication and SHOULD use configured validation-capable Grafana Dashboard resource API access even when publication is not requested.
- Read-only datasource access may be used for discovery and query validation.
- Default new dashboards to Dashboard Schema V2.
- Preserve the schema of an existing dashboard unless migration is requested.
- Preserve existing dashboard identity, unrelated panels, repository helpers, and dependency pins.
- Use the repository dashboard location, or `dashboards/<service>.jsonnet` when none exists.
- The coordinator owns all final dashboard and shared-helper edits and all real publish operations.

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
- opaque Grafana Dashboard resource API validation access/wrapper when available
- existing dashboard resource identity when applicable
- whether publication is requested
- when publication is requested: writable authentication method and folder placement when applicable

Do not place literal connection details or target identifiers into the shared contract passed to subagents. Provide an opaque access capability/reference instead.

Do not require publication intent before using an already configured Dashboard API credential/wrapper for a non-persisting dry-run validation request.

The Grafana Dashboard resource API namespace is always `default`. Do not ask for, infer, discover, or configure another Dashboard API namespace. This API namespace is unrelated to the dashboard variable named `namespace`.

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

Use `$datasource` for every Prometheus target, variable query, and annotation according to the target/pinned Dashboard V2 datasource-reference model. Never embed a discovered datasource UID.

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
- sanitized shared contract
- opaque read-only query access instructions when available

It returns selected operational questions, straightforward scoped PromQL, units, retained labels, validation results, unresolved semantics, annotation-source candidates, and isolated PromQL consultation requests when needed.

### 2. Kubernetes analysis

Delegate to `kubernetes-metrics`.

Give it only:

- workload manifests or verified workload identity
- relevant container set
- sanitized shared contract
- opaque read-only query access instructions when available

It returns health/resource questions, straightforward scoped PromQL, matching keys, container populations, validation results, availability limits, optional annotation-source candidates, and isolated PromQL consultation requests when needed.

Run application and Kubernetes analysis concurrently when the runtime can do so without duplicating large inputs.

### 3. Difficult PromQL

For each isolated consultation request, invoke `promql-expert` with only the affected operational question, metric metadata, selectors, scrape timing, candidate expression, and sanitized relevant evidence.

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

For Dashboard Schema V2, **MUST read `knowledge/grafana/grafonnet-v2.md` and `knowledge/grafana/grafonnet-builder-composition.md` before writing the source. MUST use the pinned generated Grafonnet builder whenever one exists. Hand-authored equivalents are forbidden unless the local generated API genuinely has no suitable builder or the repository documents a compatibility workaround for the exact pin. Use the canonical v13 recipes before inventing another composition pattern.**

When a verified process/container start-timestamp metric exists, read `knowledge/grafana/annotations.md`. Add an annotation only when a sparse event-like query validates without misleading duplicates or flooding; never query a continuously scraped timestamp gauge directly as an annotation.

### 6. Independent review

After rendering, delegate to `dashboard-reviewer`.

Give the reviewer:

- final Jsonnet source
- rendered JSON
- sanitized shared contract
- pinned Grafana/Grafonnet versions
- relevant raw fixture paths
- opaque read-only datasource access instructions when available
- opaque Dashboard resource API validation access/wrapper instructions when available
- existing dashboard resource identity only when needed for the operation

Never pass literal target endpoints, host/domain details, credentials, or unrelated discovered resource identifiers to the reviewer.

For Dashboard Schema V2, the reviewer MUST validate the rendered candidate against the real target Grafana with the target-advertised Dashboard resource API dry-run before returning `PASS` when validation-capable API access is configured. Read `knowledge/grafana/grafana-v2-dry-run.md`. For current stable V2 this is `dryRun=All`, not `dryRun=true`, and `fieldValidation=Strict` should be used when advertised by target Swagger.

On any target dry-run failure, the reviewer MUST read `knowledge/grafana/v2-validation-errors.md` and `knowledge/grafana/diagnostic-execution.md`, preserve the complete target error in a local scratch file, and isolate the selected schema branch before recommending a source correction. The coordinator MUST NOT accept a speculative explanation such as an unsupported layout, ambiguous discriminator, Grafana version quirk, or server bug without target-side evidence/minimal reproduction.

The reviewer MUST keep dry-run isolation bounded: one changed candidate per probe, a compact PASS/FAIL ledger, proven facts carried forward, and at most six target-side isolation probes for one validation failure. If unresolved after the budget, return `FAIL` instead of continuing exploratory self-dialogue.

The reviewer MUST also enforce `knowledge/security/output-redaction.md`. Visible target-information leakage is an independent `FAIL`.

The dry-run is validation only and must not be reported as publication. If target Grafana is configured for the task but no validation-capable Dashboard API access is available, the reviewer reports the server-side V2 validation gap rather than silently treating static checks as equivalent.

Do not give the reviewer analyst conclusions or expected findings. A worker must not approve its own output.

Fix confirmed findings in the coordinator context and render/review again when the fix can affect dashboard semantics.

### 7. Publish when requested

Publish only after the dashboard has passed the applicable local validation, target-Grafana dry-run validation, confidentiality review, and independent review.

Read:

- `knowledge/grafana/publishing-v2.md`

For Dashboard Schema V2, use the Grafana Dashboard resource API. Do not use the legacy dashboard endpoint and do not convert the dashboard to classic JSON merely to publish it.

The API contract source of truth is the target Grafana Swagger obtained through the configured opaque target access. The target Grafana Swagger wins. If the target advertises another supported structured dashboard version instead of stable V2, use that target-advertised API and schema. Never guess an API version.

Always use the Dashboard resource namespace `default`.

For stable V2 the resource operations are normally collection create, resource GET, and resource PUT under the Dashboard resource API. Confirm methods and request bodies from target Swagger before writing.

- New dashboard: use the collection create operation.
- Existing dashboard: GET it first, preserve identity/folder placement unless intentionally changed, then use the documented replace/update operation.
- Use the rendered Schema V2 resource/spec; do not blindly POST a classic DTO or arbitrary Jsonnet output envelope.
- Never create a duplicate dashboard because an update failed.
- Never expose target endpoint details, resource identifiers, credentials, or authorization/session material in visible output.

After writing, GET the resource again through the same API version under `namespaces/default` and verify the returned dashboard title, required variables, expected V2 layout, and layout element references. A write response alone is not sufficient publication verification.

## Context discipline

- Do not give subagents the complete conversation.
- Do not give subagents the complete `SKILL.md`; their registered agent definition is their role contract.
- Give each subagent only shared-contract fields and local files needed for its task.
- Sanitize target-specific context before handoff; use opaque access references.
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
- **For Dashboard V2, MUST use generated Grafonnet builders whenever the pinned library provides them; manual equivalents are not acceptable source.**
- Inspect pinned generated Grafonnet methods when uncertain; do not guess method or schema shapes.
- Preserve dependency pins.
- Keep code-managed dashboards non-editable unless repository policy explicitly requires UI editing.

## Local and target validation

Prefer repository build commands. When applicable, validate with installed local tools:

```bash
jsonnetfmt -i <dashboard.jsonnet>
jsonnet -J vendor <dashboard.jsonnet> > /tmp/dashboard.json
jq empty /tmp/dashboard.json
dashboard-linter lint --strict --config <lint-config> /tmp/dashboard.json
```

Use the repository's actual paths and commands when they differ. `jq empty` checks JSON syntax only, not Grafana schema correctness.

For Dashboard Schema V2 with configured target Grafana Dashboard API validation access, server-side dry-run validation is mandatory before review can pass. Use target Swagger, namespace `default`, and `knowledge/grafana/grafana-v2-dry-run.md`. A successful HTTP status alone is insufficient: inspect warnings and the returned resource structure.

Every target-access command MUST follow `knowledge/security/output-redaction.md`. Use an opaque configured target reference and never expose the resolved endpoint or target identifiers in the visible transcript.

If target dry-run fails, read `knowledge/grafana/v2-validation-errors.md` and `knowledge/grafana/diagnostic-execution.md` before changing source. CUE disjunction errors can list discriminator conflicts from every rejected branch; those conflicts are not evidence that the request contains multiple variants. Follow the matching branch, capture the full error locally, and use bounded target-side isolation when necessary. Do not disable strict validation or invent union-wrapper fields as a workaround.

When datasource access is available, test representative application, Kubernetes, variable, and annotation queries with explicit values replacing dashboard variables and macros. HTTP success alone is not a pass: inspect datasource errors, warnings, series count, label keys, duplicate series, representative values, and empty-result semantics. Sanitize all surfaced evidence.

For Prometheus annotations, verify that the query returns only event-like points. Every returned datapoint becomes a marker, so continuous timestamp gauges or overlapping change windows can flood or duplicate annotations.

Test one pod, multiple pods, and All where supported.

If live datasource access is unavailable, mark live-query and annotation validation `UNVERIFIED`; never infer a pass from static inspection alone.

## Completion

Report only:

- source paths changed, sanitized if they reveal target identity
- schema
- major panel groups added or changed using generic descriptions
- important omitted signals and why
- render/schema/lint status
- target-Grafana Dashboard V2 dry-run validation status when applicable
- live-query validation status
- annotation validation status when applicable
- publish verification status when requested

Never include target endpoints, host/domain data, organization/customer identifiers, cluster/environment names, dashboard/resource IDs, credentials, or session/auth material in completion output.
