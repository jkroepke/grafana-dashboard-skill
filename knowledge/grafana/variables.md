# Grafana dashboard variables

## Required variables

Create in this order:

| Name | Definition | Selection |
| --- | --- | --- |
| `datasource` | Prometheus datasource variable | single, no All |
| `namespace` | query values of `kubernetes_namespace` scoped to the application | single, `multi=false`, `includeAll=false` |
| `pod` | query values of `kubernetes_pod_name` scoped to application and namespace | multi, `includeAll=true`, empty custom All value |

Use `$datasource` for every Prometheus panel target, variable query, and annotation.

Never embed a discovered datasource UID.

## Application discovery

Prefer a continuously exposed application metric with verified fixed application selectors:

```text
namespace: label_values(<metric>{<fixed-app-selectors>}, kubernetes_namespace)
pod:       label_values(<metric>{<fixed-app-selectors>,kubernetes_namespace="$namespace"}, kubernetes_pod_name)
```

Prefer structured Prometheus label-value variable queries when the pinned Grafana/Grafonnet API supports them. `label_values(...)` is Grafana variable syntax, not standalone PromQL.

Request/event counters may not exist before first activity. Where required, union discovery with application-scoped `up` or verified KSM membership.

## Matchers

Single-value variable:

```promql
label="$namespace"
```

Multi/All variable:

```promql
label=~"${pod:regex}"
```

Use `${name:text}` for human-facing text.

Avoid `:raw` unless the complete interpolated syntax is controlled and validated.

## Additional variables

Add only when:

- semantics are verified
- cardinality is practical
- it controls a useful query/title/link/repeat

Do not expose every metric label.

Keep dependency chains shallow and acyclic. Scope child option queries by every applicable parent and fixed application identity.

## All

Enable All only with a bounded meaning. Empty custom All value expands enumerated values. Do not replace this with `.*` unless every consumer independently enforces application scope.

## Refresh

Refresh on dashboard load for time-independent option queries. Use time-range refresh only when the option query actually depends on dashboard time.

Linked child variables must refresh when parents change according to the pinned Grafana behavior.
