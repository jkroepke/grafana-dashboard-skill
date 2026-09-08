---
name: grafana-dashboard
description: Create, update, validate, and optionally publish Dashboard Schema V2 Grafonnet dashboards for Kubernetes applications and APIs on Grafana v13+. This skill does not support classic dashboards or Grafana versions below 13.
---

# Grafana Dashboard V2 for Kubernetes applications

Create or update only Dashboard Schema V2 Grafonnet dashboard resources for Grafana v13 or later. Keep application behavior prominent. Add Kubernetes signals only when they explain workload health, capacity, or resource use.

## Compatibility gate

This skill is V2-only and requires Grafana v13+.

- Require a verified Grafana version in `v<major>[.<minor>[.<patch>]]` form, with major version 13 or higher, before dispatching any specialist.
- Require a successful opaque `GET /version` check whose `gitTreeState` reports Grafana v13 or later. Ignore its Kubernetes API-style `major`, `minor`, and `gitVersion` fields.
- Create, update, validate, and publish only Dashboard Schema V2 resources (`apiVersion: dashboard.grafana.app/v2`, `kind: Dashboard`).
- Do not create, update, convert, validate, or publish classic dashboard JSON. An existing source is assessed by the designated specialist stages; if it renders to a non-V2 dashboard, stop. Classic-to-V2 migration is outside this workflow.

## Environment

This workflow runs air-gapped with a 256k context limit.

- Do not depend on internet access during normal runtime.
- Use repository files, supplied metrics/manifests, pinned local dependencies, configured Grafana/Prometheus access, and `knowledge/`.
- Treat unknown facts as unknown. Do not invent metrics, labels, workload names, recording rules, Grafonnet methods, schema fields, API routes, or credentials.
- Prefer file paths and targeted excerpts over copying large inputs into agent contexts.
- Leave raw metrics dumps and large query responses on disk.
- Mike Farah `yq` v4 is required for direct agent-authored YAML writes. Agents
  use it for YAML tickets, checkpoints, state, and stage artifacts. Checked-in
  automation may be implemented in Python; non-YAML outputs use their native
  tools.

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
- For target-validation failures requiring more than one probe, MUST read `knowledge/grafana/diagnostic-execution.md`. Use its diagnostic ledger and six-probe isolation budget.
- Prefer direct repository commands and `jq` structural slicing over repeatedly generating throwaway helper scripts.

## Runtime compatibility

Canonical subagent definitions live in `agents/` and are exposed by the repository symlinks for the primary clients OpenCode and Pi, plus existing compatibility discovery paths.

`coordinator` is the required primary/root agent for this skill. It is not a
specialist and MUST NOT be invoked as a subagent. OpenCode selects it through
the repository `opencode.json`. In Pi with `@pi-kaush/pi-agent-mode`, activate
it with `/agent coordinator` before starting a dashboard task.

Invoke specialists by agent ID:

- `application-metrics`
- `kubernetes-metrics`
- `metrics-reviewer`
- `dashboard-architect`
- `promql-builder`
- `promql-reviewer`
- `dashboard-builder`
- `dashboard-reviewer`
- `dashboard-publisher`

The repository exposes the skill through `.agents/skills/grafana-dashboard`. Keep the runtime symlink layout intact.

`@pi-kaush/pi-agent-mode` activates the persistent main-agent role but does not
provide child-agent delegation. Pi therefore also requires a compatible
subagent extension for this pipeline. When that extension has an agent-scope
option, enable project agents (`project` or `both`) so it discovers the
repository `.pi/agents` definitions.

Do not duplicate agent definitions for individual runtimes.

## Scope

- Create or update dashboard source.
- Publish/write a dashboard only when the user explicitly requests it and writable Grafana dashboard API access is available.
- Dashboard Schema V2 server-side dry-run validation is not publication and SHOULD use configured validation-capable Grafana Dashboard resource API access even when publication is not requested.
- Read-only datasource access may be used for discovery and query validation.
- Every candidate and existing-source baseline must render as a Dashboard Schema V2 resource.
- Preserve existing dashboard identity, unrelated panels, repository helpers, and dependency pins.
- Use the repository dashboard location, or
  `dashboards/<project-name>/dashboard.jsonnet` when none exists.
- `dashboard-builder` owns the single staged dashboard candidate. This workflow version does not stage helper edits, and it never writes the final destination.
- The coordinator owns dispatch, stage state, digest checks, and mechanical promotion of an approved candidate. A fresh `dashboard-publisher` performs explicitly requested publication. The coordinator MUST NOT reconstruct or manually repair dashboard source, PromQL, or API payloads.

Do not publish before rendering, validation, and independent review are complete.

## Coordinator entry gate

The coordinator's only task-specific pre-delegation activity is to configure
access with `scripts/set_workflow_env` and create and validate the sanitized run
contract. It may read the required confidentiality and coordinator-control
documentation, and check input paths, file metadata,
source baseline state/digest, pinned-version metadata, and opaque access
capabilities. It MUST NOT read or interpret raw metric/manifests/dashboard/API
contents; search them for metric names, labels, query text, panel content, or
semantics; run datasource probes; or construct any dashboard artifact other
than the run contract.

After access configuration, the coordinator's sole target-version request is
the repository's shell-free, zero-argument `scripts/grafana_version.py`. It
exits zero only for HTTP 200 and writes JSON only to stdout. Do not append,
construct, or pass target arguments. Capture stdout and stderr in neutral scratch
files. Parse only `gitTreeState`, which must be
exactly `grafana v<major>[.<minor>[.<patch>]]`; the Kubernetes API-server
`major`, `minor`, and `gitVersion` fields are not Grafana version evidence.
Do not fetch, inspect, or cache a target OpenAPI document. Do not invoke the
same `/version` request again during the run.

Once the run contract passes validation, dispatch `application-metrics` first.
It must produce a validated, non-empty application namespace-scope evidence
reference before `kubernetes-metrics` can start. Dispatch `kubernetes-metrics`
only with the application artifact as a direct input and with that exact scope
reference and digest in its ticket. The coordinator performs no overlapping
evidence gathering while either analyst runs. If an analyst, fresh subagent
context, or the runtime's subagent tool is unavailable, stop with the completed
artifact statuses and a bounded blocker. Do not substitute coordinator work for
the missing stage.

## Establish the shared contract

Before delegation, locate or record proposed facts and evidence paths without performing metric semantics or dashboard construction in the coordinator context:

- application/workload identity
- filesystem-safe project name, neutral run ID, and the absolute
  `dashboards/<project-name>/workspace` path
- candidate container and sidecar evidence
- verified Grafana version (`v13+`) and Dashboard Schema V2 compatibility
- Grafonnet revision
- absolute repository root, final `.jsonnet` path, adjacent candidate path, and source baseline digest
- shell-free render argv/cwd that emits JSON on stdout and uses one standalone `{source}` argument
- proposed cluster scope
- scrape intervals when available
- available metric-source paths/access capabilities
- proposed fixed-selector references
- configured datasource access method
- opaque Grafana Dashboard resource API validation access/wrapper when available
- `scripts/grafana_version.py` as the zero-argument `/version` command
- existing dashboard resource identity when applicable
- whether publication is requested
- when publication is requested: writable authentication method and folder placement when applicable

Create the coordinator run contract with
`scripts/create_coordinator_artifact.py run-contract`; do not reconstruct its
YAML with an ad hoc `yq` expression. The helper records the source baseline,
requires an executable render command, resolves locally locked Grafonnet
revision evidence, validates the artifact, and advances coordinator state.

Do not place literal connection details or target identifiers into the shared contract passed to subagents. Provide an opaque access capability/reference instead.

Before any target request, configure access privately with
`scripts/set_workflow_env`. If the runtime cannot invoke it without exposing
task-provided access details, stop with `MISSING_PRIVATE_CONFIG_WRITER`.

When the repository wrappers are configured, use
`scripts/prometheus_reader.py <request-file> <response-file>` for read-only
Prometheus access and `scripts/grafana_dry_run.py <resource-file>
<response-file>` for a new-dashboard Dashboard V2 create dry-run. The supplied
dry-run script does not validate an existing resource update. Treat Dashboard
API validation as configured for an existing dashboard only when a separately
supplied opaque wrapper supports the required resource GET and update dry-run,
including writing the response body to a neutral local file on HTTP failure.
Otherwise record `dashboard_api_validation: false` in the run contract and do
not substitute a collection POST or direct request. Their target, datasource selection,
proxy paths, and credentials are trusted private configuration; do not invoke
the datasource resolver, supply an endpoint or UID, or read/source configuration.
Prometheus requests may use only `query`, `query_range`, `series`, `labels`,
`label_values`, or `metadata`, with all target-identifying input kept in the
request file.

Do not require publication intent before using an already configured Dashboard API credential/wrapper for a non-persisting dry-run validation request.

The parsed `gitTreeState` establishes only Grafana v13+ eligibility. It does
not establish that the credential may create or update a dashboard, even with
`dryRun=All`; the later reviewer dry-run is the permission/admission check. A
Prometheus datasource is a separate capability and must not be inferred from
the `/version` result.

The Grafana Dashboard resource API namespace is always `default`. Do not ask for, infer, discover, or configure another Dashboard API namespace. This API namespace is unrelated to the dashboard variable named `namespace`.

Use evidence in this order:

1. local source and configuration
2. supplied metric metadata
3. verified live datasource/API data
4. local `knowledge/` contracts

A single exposition dump proves observed samples and exporter/instrumentation labels only. It does not prove historical behavior, every possible label value, or labels attached by the scrape pipeline.

Treat exposition labels and stored scrape labels separately. In this target environment, `kubernetes_namespace` and `kubernetes_pod_name` are valid stored application labels and may be attached by the scrape pipeline. Their absence from a raw `/metrics` dump does not invalidate the stored-series selector contract.

The run contract contains selector proposals and evidence references only. `metrics-reviewer` owns the approved selector/population contract consumed by every later stage.

## Required dashboard variables

Every dashboard has these variables in dependency order:

| Name | Source | Selection |
| --- | --- | --- |
| `datasource` | Prometheus datasource | single, no All |
| `namespace` | application-scoped `kubernetes_namespace` | single, no All |
| `pod` | application-scoped `kubernetes_pod_name` | multi, All enabled with empty custom All value |

Use `$datasource` for every Prometheus target, variable query, and annotation according to the target/pinned Dashboard V2 datasource-reference model. Never embed a discovered datasource UID.

These are query-contract requirements. Only `promql-builder` may instantiate them into final datasource query text.

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

For every dashboard source creation or update, the following isolated-agent pipeline is mandatory. If the runtime cannot provide fresh subagent contexts or a required agent is unavailable, stop with the completed artifact statuses; the coordinator MUST NOT absorb the missing stage. A reviewer-only read-only inspection is allowed only when that reviewer's complete prerequisite artifact chain already exists; otherwise it is an informal inspection and cannot issue a gate status. No source change may bypass staged construction and review.

Read `knowledge/workflow/workspace.md` and `knowledge/workflow/artifacts.md`
before dispatch. Use `scripts/coordinator_stage.py dispatch` to initialize the
role workspace, validate every accepted prerequisite, create its immutable
`inbox/job.yaml`, and update coordinator state. Do not hand-build tickets or
digests. Give the fresh specialist only its agent ID, ticket path, and ticket
digest. The specialist runs `coordinator_stage.py validate-ticket` before
reading assignments. Use `coordinator_stage.py accept` to verify its bounded
response, artifact, and digest. Use a fresh specialist instance at every
author/reviewer boundary. Do not create recursive subagent trees.

The ticket contains only neutral paths, expected digests, sanitized fields,
opaque access references, and transitive validation paths. Support artifacts
are validator-only unless they are direct role inputs.

The mandatory state machine is:

```text
application-metrics
  -> kubernetes-metrics (exact application namespace scope)
  -> metrics-reviewer PASS
  -> dashboard-architect PASS
  -> promql-builder PASS
  -> promql-reviewer PASS
  -> dashboard-builder candidate PASS
  -> dashboard-reviewer PASS
  -> coordinator mechanical promotion
  -> optional dashboard-publisher PASS when requested
```

Any upstream artifact change invalidates every downstream approval derived from its previous digest.

When a stage cannot produce its normal artifact, create the terminal report
with `scripts/create_coordinator_artifact.py failure-report`. Every supplied
evidence reference must identify an existing regular file inside the repository.
The helper validates the report and marks coordinator state `FAIL` or `BLOCKED`
with `next_action: complete`.

### 1. Metric inventories

Run `application-metrics` first. It discovers the exact non-empty namespace set
represented by verified application stored series and records that set only in
local namespace-scope evidence. Then run `kubernetes-metrics` with the
completed application artifact as a direct input. It may cover one or multiple
namespaces, but every Kubernetes discovery request must be limited to that
exact set; it must never perform an unconditional cluster-wide scrape or query.
If the scope cannot be verified or applied, stop the Kubernetes stage with a
bounded failure report rather than widening it. The analysts inventory observed
facts and categorize capabilities as `BUSINESS`, `PROCESS`, or `KUBERNETES` in
separate artifacts.

Analysts MUST NOT write final or candidate PromQL, variable queries, annotation queries, operational panel plans, or dashboard source. Large catalogs and raw evidence remain on disk; their visible response contains only stage status, artifact path, and digest.

For large Prometheus/OpenMetrics exposition, the analyst streams the configured
opaque reader or local evidence through `scripts/snapshot_metrics.py` on stdin.
The helper has no network, credential, or input-file interface and writes small
per-family YAML snapshots without exposing raw sample or label values to agent
context. The analyst inspects those snapshots selectively. Both metric analysts
use `records/pending/` and `records/done/` as a durable queue: after a metric
record and its `state.yaml` checkpoint are durable, move its processed work item
to `done/`; on restart, reconcile completed checkpoint entries before processing
the remaining pending items.

### 2. Independent metrics review

Dispatch `metrics-reviewer` with the inventory artifacts, expected digests, targeted raw evidence, selector facts, existing dashboard source/render paths when updating, and approved-metric budget. It independently verifies types, units, labels, lifecycle, population, availability, cardinality, supported semantics, and dependencies of every existing Prometheus query that will remain.

Only its bounded `metrics-contract.yaml` may supply metrics to downstream stages. It authors no datasource query text. On failure, route evidence defects to the owning analyst; do not repair the contract in the coordinator.

### 3. Dashboard architecture

Dispatch `dashboard-architect` with only the approved metrics contract, existing-dashboard constraints, user objective, schema constraints, and declared budgets.

It writes operational question IDs, allowed metric IDs, desired result shapes, conceptual panels/groups/layout, priorities, and omissions. It MUST NOT write datasource query text or dashboard source.

### 4. Exclusive PromQL construction

Dispatch `promql-builder` with only the approved metrics contract and dashboard plan, existing dashboard source/render paths when updating, relevant targeted evidence, and opaque read-only datasource access. It obtains selector, population, and scrape-timing facts only from the approved metrics contract and its evidence references, never from run-contract proposals.

`promql-builder` is the only agent allowed to author or change any final Prometheus datasource query text. This includes all panel targets, Prometheus variable queries, and Prometheus annotation queries. Straightforward and difficult queries have the same owner. No analyst, architect, dashboard builder, reviewer, or coordinator may add, repair, normalize, or optimize them.

The builder writes a bounded `query-pack.yaml`. Discovery and validation probes by other roles are evidence only and MUST NOT be copied into dashboard artifacts.

### 5. Independent PromQL review

Dispatch a fresh `promql-reviewer` with the exact query pack and digest, its approved inputs, targeted evidence, and opaque read-only datasource access.

The reviewer validates every query rather than a representative subset. It writes findings but never replacement expressions. A query failure returns to `promql-builder`; any revised query pack requires a new PromQL review.

Do not continue until the review artifact says `PASS` for the exact current query-pack digest. When live access is unavailable, preserve the documented `UNVERIFIED` status rather than inventing a pass.

### 6. Staged dashboard construction

Dispatch a fresh `dashboard-builder` with the approved metrics contract, dashboard plan, exact approved query pack and review, pinned local versions, existing source when applicable, repository build commands, and assigned candidate/render/manifest paths.

The builder writes and renders only the staged candidate. It MUST NOT edit the final dashboard path or publish. It copies approved query text byte-for-byte and may not create a new datasource query. If exact integration is impossible, it returns a failure artifact for the owning earlier stage.

The builder MUST read `knowledge/grafana/grafonnet-v2.md` and `knowledge/grafana/grafonnet-builder-composition.md`, use pinned generated builders whenever they exist, and use only documented exact-pin workarounds. It runs format, exact candidate-render binding, JSON, lint/schema, layout-reference, variable-contract, and query-parity checks before returning `PASS`.

### 7. Independent dashboard review

Dispatch a fresh `dashboard-reviewer` with the candidate source, rendered JSON, build manifest, dashboard plan, query pack, query-review artifact, expected digests, pinned versions, and opaque target validation access.

The reviewer checks Grafonnet/source composition, rendered schema, variables, visualization plugins, panels, layout, annotations, and exact integration of every approved query. It does not repeat semantic PromQL ownership and never writes a replacement query or source patch.

It MUST perform the stable V2 Dashboard resource API dry-run when validation-capable access is configured for the exact create or update operation. A target failure follows `knowledge/grafana/v2-validation-errors.md`; use `knowledge/grafana/diagnostic-execution.md` only when the opaque wrapper preserves the failure response and supports the required probe operations. Otherwise retain the sanitized wrapper failure as the validation result and route it back without attempting direct target requests. Dry-run validation is not publication.

Route dashboard-source findings to `dashboard-builder`. A finding requiring query changes invalidates query review and returns to `promql-builder`. A worker never approves its own output.

### 8. Mechanical promotion

Only after every required artifact is `PASS`, the coordinator verifies all current digests and confirms that the final destination still matches its recorded baseline state. It then promotes the exact reviewed candidate mechanically; it MUST NOT recreate or edit its contents.

If the final destination changed concurrently, stop rather than overwrite it. The promotion gate uses atomic no-clobber creation for a new source or atomic exchange/rollback for an existing source, then proves the final-path render is byte-identical to the reviewed render. Candidate source may not use `std.thisFile`. This workflow version does not permit shared-helper edits; block and redesign an atomic candidate-set contract when one is genuinely required.

### 9. Publish when requested

Dispatch a fresh `dashboard-publisher`. Publish only after the dashboard has passed the applicable local validation, target-Grafana dry-run validation, confidentiality review, independent review, exact final-path render verification, and mechanical promotion. The publisher may construct API requests and verify the readback, but it MUST NOT change source or query text.

Read:

- `knowledge/grafana/publishing-v2.md`

Use the Grafana Dashboard resource API. Do not use the legacy dashboard endpoint and do not convert the dashboard to classic JSON merely to publish it.

Use the repository's pinned/local stable Dashboard V2 contract with the
configured API wrapper. Do not fetch or inspect target OpenAPI/Swagger during
this workflow, and never substitute another structured API version.

Always use the Dashboard resource namespace `default`.

For stable V2 the resource operations are collection create, resource GET, and resource PUT under the Dashboard resource API. Use the pinned/local request shapes; do not retrieve target Swagger before writing.

- New dashboard: use the collection create operation.
- Existing dashboard: GET it first, preserve identity/folder placement unless intentionally changed, then use the documented replace/update operation.
- Use the rendered Schema V2 resource/spec; do not blindly POST a classic DTO or arbitrary Jsonnet output envelope.
- Never create a duplicate dashboard because an update failed.
- Never expose target endpoint details, resource identifiers, credentials, or authorization/session material in visible output.

After writing, the publisher GETs the resource again through the same API version under `namespaces/default` and verifies the returned dashboard title, required variables, expected V2 layout, and layout element references. A write response alone is not sufficient publication verification.

## Context discipline

- Do not give subagents the complete conversation.
- Do not give subagents the complete `SKILL.md`; their registered agent definition is their role contract.
- Queue each subagent's approved upstream paths/digests and assignments in its
  small immutable `inbox/job.yaml`; create and validate it with
  `scripts/coordinator_stage.py`, then give the model only its agent ID and that
  ticket path/digest.
- Sanitize target-specific context before handoff; use opaque access references.
- Every agent treats context as disposable and its assigned workspace as durable
  memory. It writes one bounded YAML record as soon as each logical item is
  resolved, then updates `state.yaml`; it never accumulates a complete result in
  context for one large final write.
- Agents assemble their stage artifact from the small records with `yq`. They
  resume from `state.yaml` and load only targeted records, never the whole work
  history. The coordinator never imports record bodies into conversation.
- Metric analysts parse large dumps once and checkpoint each family separately;
  the coordinator never imports their inventories into conversation.
- Do not paste complete Grafana frames or API responses into the coordinator context.
- Store all substantial stage results and raw requests/responses in files. Agent responses obey the status/path/digest limit in `knowledge/workflow/artifacts.md`.
- Keep rejected alternatives out of the coordinator context unless they expose a correctness issue.
- Only `dashboard-builder` writes the staged dashboard candidate. Reviewers never edit; the coordinator only verifies and mechanically promotes that exact approved file.
- Discovery or review probes may use ad hoc PromQL as private evidence, but only `promql-builder` may create or change query text that enters a dashboard artifact.
- Every Prometheus datasource query remaining in an updated dashboard, including preserved legacy queries, must be represented in and approved with the exact query pack. Explicitly non-Prometheus consumers remain outside the query pack and must be preserved unchanged by the non-Prometheus fingerprint gate. Adding, changing, or removing one is out of scope for this workflow and returns `BLOCKED` for a separate owner/review contract.
- Limit query build/review and dashboard build/review correction loops to three revisions each. On exhaustion, stop with the latest bounded failure artifact rather than growing context indefinitely.
- Treat 256k as a hard ceiling, not a target.

## Dashboard content priorities

`dashboard-architect` chooses panels by operational question, not by metric count:

1. traffic/work rate, failures, duration, application-specific outcomes
2. saturation, concurrency, queues, dependency behavior
3. readiness, resource usage, restarts, configured capacity
4. runtime, database, network, or filesystem details only when supported by useful metrics

Database panels are optional. Do not invent HTTP signals for workers or batch applications.

## PromQL requirements

`promql-builder` applies these rules to every dashboard Prometheus query and `promql-reviewer` verifies them independently:

- Apply `rate()` or `increase()` to individual counters before aggregation.
- The observed/approved metric type overrides naming convention. A declared
  gauge remains a gauge even when its name ends in `_total`; never infer counter
  semantics from `_total`, `_count`, `_sum`, HELP text, numeric values, or a
  short monotonic sample window.
- `rate()`, `irate()`, `increase()`, and `resets()` must not consume gauges,
  info, stateset, or unknown metrics. A name/type contradiction is an
  instrumentation blocker, not permission to repair the type in PromQL.
- Use `$__rate_interval` for counter rates.
- Use `$__range` for selected-period totals when that is the intended question.
- `rate()` and `increase()` need enough samples to calculate a change; a newly observed series with only one sample produces no useful increase.
- Do not silently convert missing data to zero.
- Distinguish absent instrumentation, failed scraping, zero activity, stale series, and missing configuration.
- Do not invent health thresholds.
- Keep evidence and uncertainty in the query pack; reject a query that cannot be supported rather than delegating authorship or guessing.

## Kubernetes requirements

The Kubernetes analyst, metrics reviewer, PromQL builder, and PromQL reviewer read `knowledge/kubernetes/metrics.md` when Kubernetes context is used.

- Keep application metric labels separate from native KSM/cAdvisor labels.
- Exclude cAdvisor `container=""` and `container="POD"` for container resource calculations.
- Match identical container populations before comparing usage with requests or limits.
- Do not interpret missing or zero limits as numeric capacity.
- Do not guess workload names from pod-name regexes when owner relationships are available.
- Prefer verified scheduler pod resource metrics for pod-level scheduling capacity when available; retain KSM container metrics for per-container comparisons.

## Grafana and Grafonnet requirements

`dashboard-builder` applies these construction rules and `dashboard-reviewer` verifies them independently:

- Prefer built-in visualizations.
- For V2, use layout kinds supported by the pinned schema, such as `AutoGridLayout`, `GridLayout`, `RowsLayout`, and `TabsLayout`.
- Prefer `AutoGridLayout` for similarly sized panels and `GridLayout` only for deliberate size/position differences.
- Use tabs or rows only when each section contains enough useful content.
- **MUST use generated Grafonnet builders whenever the pinned library provides them; manual equivalents are not acceptable source.**
- Inspect pinned generated Grafonnet methods when uncertain; do not guess method or schema shapes.
- Preserve dependency pins.
- Keep code-managed dashboards non-editable unless repository policy explicitly requires UI editing.

## Local and target validation

Local dashboard construction checks belong to `dashboard-builder`; independent repetition, target admission, and query-integration checks belong to `dashboard-reviewer`. Live PromQL validation belongs to `promql-builder` and `promql-reviewer`.

Prefer repository build commands. When applicable, validate with installed local tools:

```bash
jsonnetfmt -i <dashboard.jsonnet>
jsonnet -J vendor <dashboard.jsonnet> > <dashboard-builder-run-dir>/evidence/rendered.json
jq empty <dashboard-builder-run-dir>/evidence/rendered.json
dashboard-linter lint --strict --config <lint-config> <dashboard-builder-run-dir>/evidence/rendered.json
```

Use the repository's actual paths and commands when they differ. `jq empty` checks JSON syntax only, not Grafana schema correctness.

With configured target Grafana Dashboard API validation access for the exact
create or update operation, server-side dry-run validation is mandatory before
review can pass. Use the pinned/local stable V2 contract, namespace `default`, and
`knowledge/grafana/grafana-v2-dry-run.md`. A successful HTTP status alone is
insufficient: inspect warnings and the returned resource structure. Do not
fetch target OpenAPI/Swagger; `/version` is the only target-version request.

Do not replace the configured local command with direct `curl`, a guessed
`GRAFANA_URL`, or an environment scan. The command is the access boundary for
targets that are reachable only through a local proxy, tunnel, or authenticated
helper.

Every target-access command MUST follow `knowledge/security/output-redaction.md`. Use an opaque configured target reference and never expose the resolved endpoint or target identifiers in the visible transcript.

If target dry-run fails, read `knowledge/grafana/v2-validation-errors.md` before changing source. Read `knowledge/grafana/diagnostic-execution.md` and use bounded target-side isolation only when the opaque wrapper preserves the failed response and supports those probe operations. Otherwise retain the sanitized wrapper failure locally and return it as a validation failure; do not bypass the wrapper with a direct request. CUE disjunction errors can list discriminator conflicts from every rejected branch; those conflicts are not evidence that the request contains multiple variants. Do not disable strict validation or invent union-wrapper fields as a workaround.

When datasource access is available, `promql-reviewer` tests every approved application, Kubernetes, variable, and annotation query with explicit values replacing dashboard variables and macros. HTTP success alone is not a pass: inspect datasource errors, warnings, series count, label keys, duplicate series, representative values, and empty-result semantics. Sanitize all surfaced evidence.

For every Dashboard V2 Prometheus `QueryVariable`, inspect the rendered plugin-specific query payload. On the documented v13 pin, require non-empty `spec.query.spec.query`, the expected `qryType`, and the Prometheus variable-editor `refId`. Do not accept `spec.query.spec.expr` as a substitute. Target schema admission alone is insufficient because the generic DataQuery schema does not prove that the Prometheus variable editor can deserialize the plugin payload.

For Prometheus annotations, verify that the query returns only event-like points. Every returned datapoint becomes a marker, so continuous timestamp gauges or overlapping change windows can flood or duplicate annotations.

`promql-reviewer` tests one pod, multiple pods, and All where supported.

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
