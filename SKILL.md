---
name: grafana-dashboard-from-metrics
description: Create or update local Grafonnet dashboards for Kubernetes applications and APIs from Prometheus or OpenMetrics exposition dumps. Use application metrics first, with optional Kubernetes health and resource context. Default to Dashboard Schema V2. Scope covers dashboard source and validation, not distribution.
---

# Grafana dashboards for Kubernetes applications

Create or update useful application dashboards as local Jsonnet source using Grafonnet. Keep application behavior prominent; add Kubernetes metrics to explain workload health and resource use.

## Scope and output

- Create dashboard source or update existing source. Stop after local validation and reporting; publishing, importing, provisioning, API writes, and distribution are outside this skill.
- Default new dashboards to **Dashboard Schema V2**. Preserve classic schema when updating an existing classic dashboard unless migration is requested. If a known target cannot support the requested schema, explain the incompatibility before choosing another schema.
- Preserve existing dashboard identity, unrelated panels, repository helpers, and pinned dependencies. Do not replace the entire dashboard for a focused update.
- Use the repository's source location, or `dashboards/<service>.jsonnet` when none exists. Create a `.libsonnet` helper only when it meaningfully removes duplication.
- Read-only access to an existing Grafana or Prometheus-compatible datasource may support inspection and query validation. Credentials do not authorize dashboard writes. Keep credentials out of generated files.

## 1. Establish the input and target contract

Inspect the supplied metrics and relevant local manifests, dashboard source, dependency lockfiles, and build commands. Preserve the supplied input files.

Record these facts before choosing panels:

| Fact | Evidence |
| --- | --- |
| Application and workload identity | Manifests, Helm values, scrape configuration, verified live labels, or explicit user input |
| Application containers and sidecars | Pod template or equivalent verified source |
| Grafana version, dashboard schema, Grafonnet revision | Local configuration and dependencies; mark unavailable facts as unknown |
| Cluster scope | A datasource restricted to one cluster, or an established fixed cluster selector |
| Scrape interval per metric source | Scrape configuration or verified datasource/query settings |
| Available metric sources | Supplied dumps, recording rules, and optional live inspection |

Use this evidence order: local configuration and source, supplied metric metadata, verified live data, then documented defaults here. Ask a focused question when unresolved application or cluster identity would change which workload is shown. Omit an optional panel when its semantics cannot be established.

Do not invent metric names, label meanings, container names, recording rules, Grafonnet methods, or deployment names. A single exposition dump establishes observed samples, not historical behavior or the availability of every possible label value.

### Metric inventory

Parse metric families, `TYPE`, `HELP`, `UNIT`, sample labels, observed values, and family members. Missing `TYPE` means unknown/untyped; a numeric sample alone does not establish a counter. Validate exposition with an installed format-compatible parser or `promtool check metrics` when appropriate.

Classify each raw metric reference:

| Source | Permitted use |
| --- | --- |
| `APP` | Application metrics present in the dump or verified live data |
| `KSM` | Documented kube-state-metrics state, readiness, restarts, requests, and limits |
| `KUBELET` | Documented kubelet/cAdvisor actual resource usage and pressure |
| `SCRAPE` | Prometheus-generated metrics such as `up`, with verified target selectors |
| `SCHEDULER` | Documented effective pod resource metrics already collected in the environment |
| `RECORDING_RULE` | Rules present in the repository or verified datasource, with known semantics |

Documented Kubernetes metric contracts permit generating support panels without a Kubernetes dump. Mark their availability as unverified until queried. Do not add a new scrape or recording-rule dependency as part of dashboard generation.

## 2. Define selectors and variables once

Every dashboard has these three required dashboard-scope variables, in dependency order:

| Name | Definition | Selection |
| --- | --- | --- |
| `datasource` | Prometheus datasource variable | Single; no All |
| `namespace` | Query values of `kubernetes_namespace`, scoped to this application | Single; `multi=false`, `includeAll=false` |
| `pod` | Query values of `kubernetes_pod_name`, scoped to this application and selected namespace | Multi; `includeAll=true`; custom All value empty |

Use `$datasource` for every Prometheus panel target, variable query, and annotation. In classic dashboards, also set the panel datasource; in V2, use the schema's datasource reference on each data query. Never embed a discovered datasource UID into generated dashboard queries.

Use query types supported by the pinned datasource plugin. Prefer structured Prometheus **Label values** queries when the pinned Grafana and Grafonnet APIs support them. Use classic `label_values(...)` only for compatibility; it is Grafana variable syntax, not standalone PromQL. Refresh on dashboard load unless the option query depends on the dashboard time range; linked child variables refresh when a parent changes.

For a verified application metric with sufficient application identity:

```text
namespace: label_values(<metric>{<fixed-application-selectors>}, kubernetes_namespace)
pod:       label_values(<metric>{<fixed-application-selectors>,kubernetes_namespace="$namespace"}, kubernetes_pod_name)
```

Do not assume a generic family such as `process_start_time_seconds` or `http_requests_total` identifies one application. Use verified fixed selectors where needed. A fixed `job` or other label matcher is permitted; it is not a dashboard variable. An application-specific metric family can supply identity when that uniqueness is established.

Apply the same application population to all panels:

```promql
# Application metrics: add verified fixed selectors when needed.
<metric>{kubernetes_namespace="$namespace",kubernetes_pod_name=~"${pod:regex}"}

# Kubernetes support metrics: their native workload labels.
<metric>{namespace="$namespace",pod=~"${pod:regex}"}
```

An empty custom All value expands the enumerated application pods. Do not substitute `.*` unless every affected query has independent workload scoping. Disable custom variable values where supported to keep normal UI selection bounded. This is a usability control, not authorization; datasource access controls protect data. When URL-supplied values must not move a dashboard outside its application, enforce that boundary in affected consumers with verified fixed selectors or workload-membership joins.

Treat the three required variables as a baseline, not the complete variable model. Add another variable only when its meaning and source are verified, its option cardinality is practical, and it controls a useful query, title, link, or bounded panel repeat. Do not expose every available metric label.

| Variable type | Use |
| --- | --- |
| Query | Dynamic, bounded application dimensions such as route template, operation, status class, method, queue, topic, or container. Scope its option query by fixed application identity and every applicable parent variable. |
| Custom | A small, stable, closed choice set. Do not copy dynamic label values into source. |
| Interval | An intentional user-selected semantic window. Do not replace `$__rate_interval` for counter rates or `$__interval` for automatic display resolution. |
| Constant | A hidden reusable fixed value only when a Jsonnet local or repository helper is unsuitable. Never store secrets in variables. |
| Switch | A meaningful binary query or display behavior, after confirming target-version and schema support. |
| Text box or datasource-wide filter | Avoid by default. Free-form or high-cardinality input and filters applied to every query can bypass or conflict with the application's mixed label contracts. Add only for a verified requirement and never interpolate free-form input with `:raw`. |

Order parents before children and keep dependency chains shallow and acyclic. Use exact matchers for single-value variables and `=~"${name:regex}"` for multi-value or All variables. Use `${name:text}` for human-facing text. Keep viewer-facing variables URL-synchronized so links preserve context; opt out only for an internal fixed value that must not be user-overridden. Avoid `:raw` unless the complete interpolated syntax is controlled and validated.

Enable All only when it has a clear, bounded meaning. If enumerating many values creates an impractically long expression, disable All or use a wildcard only when every consumer independently enforces application scope. Validate defaults, parent changes, URL-restored values, and each supported single, multi, and All selection.

Application labels `kubernetes_namespace` and `kubernetes_pod_name` are this environment's scrape-time contract; they need not appear in raw application exposition. KSM/cAdvisor workload identity comes from native `namespace`/`pod` labels unless verified relabeling establishes otherwise. Exporter scrape labels may describe the exporter itself, not the workload represented by the metric.

If multiple clusters share a datasource, apply a verified fixed cluster selector consistently across variable queries, panels, annotations, and joins. Do not aggregate distinct clusters merely because namespace and pod names match.

### Include workloads with failed scraping

Prefer a continuously exposed metric for normal discovery; request counters may not exist before first activity. Where available, union application discovery with application-scoped `up` targets or verified KSM workload membership so pods that never exposed application metrics can still be selected. Normalize native labels to the required variable labels in a query-result expression when necessary.

Use verified owner relationships or allowed workload labels for KSM discovery, not a guessed pod-name regex. Resolve Deployment ownership through ReplicaSets when needed. If no such source exists, report that discovery covers observed application series only. Test historical selection where retention allows it.

## Work allocation for a 256k context budget

Use a coordinator with bounded specialist tasks when sub-agents are available and the work involves a large dump, several metric sources, or a substantial dashboard update. Handle a small, focused edit directly. Check that the runtime actually provides separate agent contexts; delegation is not a substitute for controlling what each context receives.

The coordinator completes the input and selector contracts above before delegating. It owns schema choice, variables, shared selectors, dashboard identity, layout, integration, and final source edits. Keep these decisions in one compact local contract that every worker receives. Workers report contradictions or missing evidence instead of independently changing the contract.

| Task | Minimum input | Return to coordinator |
| --- | --- | --- |
| Application analysis | Application metric inventory and relevant raw families; shared contract | Prioritized application questions, exact scoped PromQL, units, retained labels, and unresolved semantics |
| Kubernetes analysis | Workload manifests; relevant KSM/kubelet/scrape evidence; shared contract | Health/resource queries, container populations, matching keys, and availability limits |
| Independent validation, after integration | Final Jsonnet and rendered JSON, shared contract, pinned dependencies, relevant raw fixtures | Concrete failures with file/query references and actual validation results |

Run the two analysis tasks concurrently only when the local runtime can support them. Run rendering and validation after their results are integrated; avoid concurrent memory-heavy Jsonnet renders. Give the validator the artifacts and requirements, not the analysts' conclusions or a list of expected findings. Do not use a sub-agent to approve its own output.

Keep context bounded:

- Leave raw dumps on disk. Parse an inventory, then retrieve selected families with their metadata and representative label sets. Do not truncate input blindly or discard rare error/restart families merely because they occur late in a file.
- Give workers fresh contexts with file paths, the shared contract, the relevant skill sections, and a specific deliverable. Do not fork the entire conversation or attach every metric source to every worker.
- Inspect generated Grafonnet libraries with targeted searches and small excerpts. Do not load an entire generated API file just to find one method.
- Return compact findings: metric/source evidence, query, unit, population, and uncertainty. Refer to local files for large results rather than pasting them into the coordinator's history.
- Use explicit file ownership. Analysis workers return proposals; the coordinator writes final dashboard files. Give a worker a separate scratch file only when its output genuinely needs one. No concurrent edits to shared helpers or final source.
- Account for instructions, history, tool output, and the final response within the 256k limit. Keep room for integration and validation; a context window is a ceiling, not a target to fill.
- Bound delegation to these useful roles; avoid recursive agent trees. Reuse a worker only for a concrete unresolved issue. If delegation is unavailable, perform the same focused passes sequentially with compact notes.

## 3. Select operational questions and layout

Choose panels by useful questions, not by metric count:

1. Traffic or work rate, failures, duration, and application-specific outcomes.
2. Saturation, concurrency, queue backlog, and dependency behavior.
3. Pod readiness, resource usage, restarts, and configured capacity.
4. Runtime, database, network, or filesystem details only when the available metrics make them useful.

Choose the visualization from the question and returned data shape:

| Question or data shape | Visualization | Guidance |
| --- | --- | --- |
| Numeric change over time | Time series | Default for rates, latency quantiles, backlog, concurrency, CPU, memory, and restart trends. Use a range query. |
| Current or selected-period value | Stat | Use for a few important instant values or explicit reductions such as events during `$__range`; state the reduction. |
| Value relative to a meaningful range | Gauge or bar gauge | Use a gauge for one or a few values and a bar gauge for comparisons. Configure meaningful bounds; do not let observed dataset bounds imply capacity. |
| Duration in discrete states | State timeline | Use for readiness, availability, leader state, or lifecycle phases. Preserve gaps as unknown. Use status history instead when every periodic observation must remain a separate cell. |
| Distribution during a period or over time | Histogram or heatmap | Use a histogram only when the query returns raw observations or a verified pre-bucketed frame for one period; do not bin cumulative counter values. Use a heatmap for change over time from correctly transformed histogram buckets or another target-supported histogram representation. |
| Comparison of bounded categories | Bar chart | Require a categorical string/time field plus numeric fields. If Prometheus returns separate labeled series, use a bar gauge or table, or a verified labels-to-fields transformation. Use a time-series panel rendered as bars for dense time-based data. |
| Exact label-rich values | Table | Use for diagnostic per-pod or per-container detail with several fields, not as the primary overview. |
| Mutually exclusive parts of one additive whole | Pie chart | Use sparingly; do not use for unrelated or overlapping series, or for trends. |

Prefer built-in visualizations. Use a panel plugin only when it is already installed or pinned for the target and materially improves the question. Do not reduce away a time dimension needed for diagnosis or turn a continuous signal into states without established boundaries.

For workers and batch applications, use work completion, backlog, retries, and duration instead of inventing HTTP signals. Database panels are optional and require actual client, pool, query, or database metrics. Runtime signals such as GC or heap usage are useful when they explain application behavior.

Use a compact overview followed by investigative charts. Keep titles, descriptions, units, and legends factual. Avoid grouping by unbounded URLs, raw paths, IDs, messages, or traces. Preserve bounded route templates when their semantics and cardinality are established.

For V2, prefer AutoGrid for panels with similar sizes. Use a custom grid for deliberate width/height differences. Introduce Application, Kubernetes, or Runtime tabs only when each has enough useful content; omit empty sections and keep nesting shallow. A small dashboard can use one layout. Use classic rows only for classic updates.

Distinguish zero activity, failed scraping, absent instrumentation, and missing configuration. Do not apply blanket `or vector(0)`, map missing series to healthy, or hide required health panels merely because they return no data. Without a supplied SLO or known limit, avoid inventing green/red health thresholds.

## 4. Build PromQL with the intended meaning

### Time windows and query mode

| Question | Expression strategy | Query mode |
| --- | --- | --- |
| Current rate or latency trend | `rate(counter[$__rate_interval])` | Range for trends; instant for current stats |
| Count during the selected dashboard period | `increase(counter[$__range])` | Instant at the selected end time |
| Explicit rolling calculation | Use the intended named duration | Match the question |
| Restart or start events | Follow the annotation section below | Event-oriented range query |

Use `$__rate_interval` for `rate()` and `irate()`; do not impose it on every range vector. Match query Min step to the source's known scrape interval where sources differ. Do not replace missing scrape configuration with a guessed claim of correctness.

Counter functions need historical samples and may extrapolate. A counter first observed at 5 does not establish when those five events happened. Do not silently add its initial value to an increase. A single dump cannot validate rates, resets, or event counts.

### Aggregation and errors

- Apply `rate()` or `increase()` to individual counters before aggregation.
- Choose gauge aggregation from meaning. Do not sum replicated cluster-wide gauges or average per-pod percentiles as an application percentile.
- Derive errors only from established metric/label semantics. Use the same population and grouping in numerator and denominator.
- Preserve no-data when the denominator is absent or traffic is zero. Fill an absent error series with zero only when instrumentation semantics establish that absence means no errors and the matching traffic series exists; preserve its labels.
- Do not clamp denominators to arbitrary positive constants to make ratios appear valid.

### Histograms and summaries

Scoped `h` below denotes a verified duration family with all required selectors applied:

```promql
# Classic histogram p95: retain le plus any intended grouping labels.
histogram_quantile(0.95, sum by (le) (rate(h_bucket[$__rate_interval])))

# Native histogram p95: only when native samples are verified.
histogram_quantile(0.95, sum(rate(h[$__rate_interval])))

# Classic histogram mean: apply only with a positive matching denominator.
sum(rate(h_sum[$__rate_interval])) / sum(rate(h_count[$__rate_interval]))
```

Do not invent `_bucket` series for native histograms. A text dump may not describe the native representation stored in Prometheus. Summary quantiles belong to their original populations; display them per instance/pod rather than combining them into an application quantile.

## 5. Add Kubernetes context with consistent populations

Use this metric map, subject to the source and selector contract above:

| Signal | Metric or calculation | Unit |
| --- | --- | --- |
| CPU usage | `rate(container_cpu_usage_seconds_total[$__rate_interval])` | CPU cores |
| Memory | `container_memory_working_set_bytes` | Bytes; working set, not exact OOM headroom |
| Requests / limits | `kube_pod_container_resource_requests` / `kube_pod_container_resource_limits` | `resource="cpu",unit="core"` or `resource="memory",unit="byte"` |
| Readiness | `kube_pod_status_ready{condition="true"}` | Ready / not ready |
| Container restarts | `increase(kube_pod_container_status_restarts_total[<window>])` | Restarts in the stated window |
| CPU throttling | Rate of `container_cpu_cfs_throttled_periods_total` / rate of `container_cpu_cfs_periods_total` | Fraction of throttled periods, not CPU time lost |
| OOM activity | `increase(container_oom_events_total[<window>])`, if collected | Events in the stated window |
| Replicas | Matching workload-kind KSM families | Desired / ready / available |

Apply namespace/pod scope and container selection before aggregation. Exclude cAdvisor `container=""` and `container="POD"` for container resource calculations. Prefer the verified application container set. When only total pod scope is known, include regular sidecars and label the panel as total pod usage; do not label it application-container usage.

For usage/request/limit comparisons:

1. Select identical containers on numerator and denominator. Keep `(namespace,pod,container)` identity, plus cluster scope when applicable, until matching is resolved.
2. Check duplicate scrape paths or exporter replicas. Do not sum duplicate observations or apply a generic `max` deduplication without understanding their identity.
3. Require a positive denominator for every included container before displaying a whole-pod utilization ratio. A missing or zero limit is not unlimited capacity expressed numerically.
4. If coverage is incomplete, show usage and configured resources separately, or explicitly show only the matched limited-container population. Do not divide full-pod usage by a partial set of limits.
5. Use 0–1 percent units for a raw ratio, or multiply by 100 and use 0–100 units. Usage/request can exceed 100%; requests are not ceilings.

Effective pod resources from already-collected scheduler metrics can differ from a sum of regular containers. Use them only when that meaning matches the panel; do not mix them into application-container ratios.

Deployment/StatefulSet/DaemonSet replica panels need the corresponding verified workload name and metric family. Label workload-wide panels as such because selecting a subset of pods does not change desired replicas. Separate current-state instant panels from historical range panels.

## 6. Annotate process starts and restarts

When a verified process/application start timestamp exists, include a start-event annotation using that metric and the required datasource/application scope. Confirm its units and meaning from metadata; do not use an unrelated timestamp.

Prefer mapping the metric's **value** (Unix seconds) to event time using the target Grafana/Prometheus plugin's supported timestamp-value option or equivalent verified mapping. Query across the dashboard period, retain distinct observed start timestamps and pod identity, and verify repeated samples produce one marker per process start. Check range filtering and seconds-to-milliseconds handling. Use the actual pinned schema; do not guess annotation fields.

This approach represents observed process starts, including the first observation of a replacement pod. Label it “Process started”; it does not by itself prove a container restart, pod replacement, or rollout cause. Preserve distinct process identity when multiple processes expose the gauge.

If timestamp-value mapping is unavailable, the limited fallback is:

```promql
changes(process_start_time_seconds{
  kubernetes_namespace="$namespace",kubernetes_pod_name=~"${pod:regex}"
}[<verified-short-window>]) > 0
```

Add any fixed application/cluster selectors. This detects value changes **within the same complete label set**. It does not detect a new series created by a replacement pod or changed scrape identity. Label this fallback “Observed process restart”; document its coverage. Where supported, supplement it with verified KSM pod/container start timestamps using the same event-time mapping.

Choose the fallback window from scrape timing and query step, not panel-rate smoothing alone. A positive rolling window can generate duplicate markers. If the target mapping or event behavior cannot be validated, keep the annotation definition disabled with a precise reason instead of presenting it as working restart detection.

Validate these cases when time-series fixtures or live history are available: same-label restart, replacement pod/new label set, and repeated scrapes of an unchanged timestamp. Do not claim coverage of starts never observed by monitoring, or multiple starts between scrapes. KSM restart-count panels are separate signals, not a substitute for timestamp semantics.

## 7. Implement and validate locally

Use the pinned generated `grafana/grafonnet` API. Inspect unfamiliar methods and their returned patch shape: a nested layout method may return a patch for the whole dashboard, not a standalone layout object. A generic schema field may require a schema-checked Jsonnet object where the API exposes no typed builder. Do not wrap classic panels in an invented V2 envelope.

Preserve dependency pins. When bootstrapping dependencies is needed and permitted by the environment, resolve a compatible Grafonnet revision and record it in the lockfile. Do not silently use an unrelated newer schema or replace an existing pin. Prefer repository build commands over the generic commands below.

```bash
jsonnetfmt -i dashboards/application.jsonnet
jsonnet -J vendor dashboards/application.jsonnet > /tmp/application-dashboard.json
jq empty /tmp/application-dashboard.json
dashboard-linter lint --strict --config dashboards/.lint /tmp/application-dashboard.json
```

Run installed tools where applicable; report missing tooling and incomplete checks. Formatting and linting availability do not excuse claiming that unrendered source is validated. `jq empty` checks JSON syntax, not Grafana schema correctness.

For the three-variable environment, merge these narrow exclusions into an existing linter configuration, or create `dashboards/.lint`. The refresh exclusion is appropriate only after checking every query variable individually: use `onTimeRangeChanged` for each time-dependent option query and `onDashboardLoad` otherwise. The linter rule cannot express that distinction.

```yaml
exclusions:
  template-on-time-change-reload-rule:
    reason: Time-independent label queries refresh on dashboard load and parent changes.
  template-job-rule:
    reason: Application identity uses verified fixed selectors and namespace/pod variables.
  template-instance-rule:
    reason: Pod selection uses kubernetes_pod_name.
  target-job-rule:
    reason: Sources have different job labels; workload scope is validated separately.
  target-instance-rule:
    reason: Queries use application workload identity rather than a shared instance label.
```

Set code-managed dashboards non-editable unless the repository explicitly requires UI editing. Fix datasource, PromQL, and schema errors instead of suppressing them. Inspect the installed linter's version and rule behavior; if a valid selected-period calculation needs an exception, scope it to that panel with a semantic reason. Pass the config path explicitly because the rendered JSON is outside the repository.

Check meaningful invariants in the rendered output: unique panel IDs, V2 layout references resolving to elements, correct schema, variable types, dependencies, and refresh modes, datasource references, query populations, units, query modes, and annotation coverage. Validate against an available target-version schema as well as rendering.

When an existing datasource is accessible, query representative application, resource, variable, and annotation expressions without modifying dashboards. Resolve dashboard variables and macros in temporary validation requests. Check per-query errors, warnings, labels, duplicate series, and empty results; HTTP success alone is insufficient. Test one pod, multiple pods, All, and a second namespace where available. For offline validation, report documented contracts separately from tested behavior.

## Completion

Report source paths, schema, the main panel groups changed, important omitted signals, and validation results. State separately whether source rendered, schema/lint checks passed, queries returned expected series, and annotations were checked. Keep the response concise; do not repeat the entire workflow.

## Executable example

This small example exercises the required variables and both schema paths. It assumes a fixture where `demo_work_total` uniquely identifies the application, a single-cluster datasource, and known namespace `demo`. The fixture has no process-start metric, so it needs no annotation. Replace fixture assumptions with verified application facts when adapting it.

The import is intentionally versioned. The shared example uses classic `label_values(...)` so one query string serves both schema paths; generated dashboards should use structured Label values queries when their pinned APIs support them. Both schema paths rendered with Grafonnet revision `41e6bfcbe4ef1054298ffff8664f1354c897dd2d`, directory `gen/grafonnet-v13.0.0`, and Jsonnet 0.22.0, and passed dashboard-linter 0.3.0 with the exclusions above. These checks do not establish Grafana UI or live-query behavior.

Save the block as `example.jsonnet`. With that Grafonnet dependency available through the vendor path, run `jsonnet -J vendor --ext-str schema=v2 example.jsonnet`; use `schema=classic` only for the classic example.

```jsonnet
local g = import 'github.com/grafana/grafonnet/gen/grafonnet-v13.0.0/main.libsonnet';
local ns = 'label_values(demo_work_total, kubernetes_namespace)';
local pods = 'label_values(demo_work_total{kubernetes_namespace="$namespace"}, kubernetes_pod_name)';
local expr = 'sum(rate(demo_work_total{kubernetes_namespace="$namespace",kubernetes_pod_name=~"${pod:regex}"}[$__rate_interval]))';

local classic =
  local v = g.dashboard.variable;
  local q(name, query) =
    v.query.new(name, query)
    + v.query.withDatasource('prometheus', '$datasource')
    + v.query.refresh.onLoad()
    + { allowCustomValue: false };
  g.dashboard.new('Demo work')
  + g.dashboard.withUid('demo-work')
  + g.dashboard.withEditable(false)
  + g.dashboard.withVariables([
    v.datasource.new('datasource', 'prometheus')
    + v.datasource.generalOptions.withLabel('Data source'),
    q('namespace', ns)
    + v.query.selectionOptions.withMulti(false)
    + v.query.selectionOptions.withIncludeAll(false)
    + v.query.generalOptions.withCurrent('demo'),
    q('pod', pods)
    + v.query.selectionOptions.withMulti(true)
    + v.query.selectionOptions.withIncludeAll(true)
    + v.query.generalOptions.withCurrent(['All'], ['$__all']),
  ])
  + g.dashboard.withPanels([
    g.panel.timeSeries.new('Work / sec')
    + g.panel.timeSeries.panelOptions.withDescription('Completed work per second across selected pods.')
    + g.panel.timeSeries.queryOptions.withDatasource('prometheus', '$datasource')
    + g.panel.timeSeries.queryOptions.withTargets([
      g.query.prometheus.new('$datasource', expr)
      + g.query.prometheus.withRefId('A')
      + g.query.prometheus.withRange(true)
      + g.query.prometheus.withInstant(false),
    ])
    + g.panel.timeSeries.standardOptions.withUnit('ops')
    + g.panel.timeSeries.gridPos.withW(24)
    + g.panel.timeSeries.gridPos.withH(8),
  ]);

local d = g.apps.dashboard.v2;
local dq(spec) = {
  kind: 'DataQuery', group: 'prometheus', version: 'v0',
  datasource: { name: '$datasource' }, spec: spec,
};
local queryVar(name, query, multi, current) = {
  kind: 'QueryVariable',
  spec: {
    name: name, label: name, description: '', hide: 'dontHide',
    query: dq({ query: query, refId: 'variable' }),
    refresh: 'onDashboardLoad', regex: '', sort: 'alphabeticalAsc',
    multi: multi, includeAll: multi, allValue: '', allowCustomValue: false,
    current: current, options: [], skipUrlSync: false,
  },
};
local grid = d.spec.layout.AutoGridLayoutKind;
local v2 = d.new('demo-work', 'Demo work') + d.withSpec({
  title: 'Demo work', description: 'Work completed by the demo application.',
  editable: false, cursorSync: 'Off', preload: false,
  annotations: [], links: [], tags: ['application'],
  timeSettings: {
    from: 'now-1h', to: 'now', timezone: 'browser', autoRefresh: '',
    autoRefreshIntervals: ['30s', '1m', '5m'],
    hideTimepicker: false, fiscalYearStartMonth: 0,
  },
  variables: [
    { kind: 'DatasourceVariable', spec: {
      name: 'datasource', label: 'Data source', hide: 'dontHide',
      pluginId: 'prometheus', regex: '', multi: false, includeAll: false,
      current: { text: '', value: '' }, options: [], refresh: 'onDashboardLoad',
      skipUrlSync: false, allowCustomValue: false,
    } },
    queryVar('namespace', ns, false, { text: 'demo', value: 'demo' }),
    queryVar('pod', pods, true, { text: ['All'], value: ['$__all'] }),
  ],
  elements: {
    work: { kind: 'Panel', spec: {
      id: 1, title: 'Work / sec',
      description: 'Completed work per second across selected pods.', links: [],
      data: { kind: 'QueryGroup', spec: {
        queries: [{ kind: 'PanelQuery', spec: {
          refId: 'A', hidden: false,
          query: dq({ expr: expr, refId: 'A', range: true, instant: false }),
        } }], transformations: [], queryOptions: {},
      } },
      vizConfig: { kind: 'VizConfig', group: 'timeseries', version: '13.0.0', spec: {
        options: {}, fieldConfig: { defaults: { unit: 'ops' }, overrides: [] },
      } },
    } },
  },
})
+ grid.withKind()
+ grid.spec.withMaxColumnCount(2)
+ grid.spec.withColumnWidthMode('standard')
+ grid.spec.withRowHeightMode('standard')
+ grid.spec.withItems([
  grid.spec.items.withKind()
  + grid.spec.items.spec.withElement({ kind: 'ElementReference', name: 'work' }),
]);

local schema = std.extVar('schema');
assert schema == 'v2' || schema == 'classic' : 'schema must be v2 or classic';
if schema == 'classic' then classic else v2
```

## Maintained references

- Grafonnet API and source: https://github.com/grafana/grafonnet
- Dashboard Schema V2: https://grafana.com/docs/grafana/latest/observability-as-code/schema-v2/
- Dashboard variables: https://grafana.com/docs/grafana/latest/visualizations/dashboards/variables/
- Variables and rate intervals: https://grafana.com/docs/grafana/latest/datasources/prometheus/template-variables/
- Visualization selection: https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/visualizations/
- Annotation behavior: https://grafana.com/docs/grafana/latest/datasources/prometheus/annotations/
- PromQL semantics: https://prometheus.io/docs/prometheus/latest/querying/functions/
- KSM workload metrics: https://github.com/kubernetes/kube-state-metrics/tree/main/docs/metrics/workload
- cAdvisor metrics: https://github.com/google/cadvisor/blob/master/docs/storage/prometheus.md
- Dashboard linter: https://github.com/grafana/dashboard-linter
