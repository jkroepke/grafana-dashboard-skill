# Grafana dashboard variables

## Required variables

Create in this order:

| Name | Definition | Selection |
| --- | --- | --- |
| `datasource` | Prometheus datasource variable | single, no All |
| `namespace` | query values of `kubernetes_namespace` scoped to the application | single, `multi=false`, `includeAll=false` |
| `pod` | query values of `kubernetes_pod_name` scoped to application and namespace | multi, `includeAll=true`, empty custom All value |

Restrict `datasource` to Prometheus datasources. Use `$datasource` for every Prometheus panel target, variable query, and annotation.

Never embed a discovered datasource UID.

## Application discovery

Prefer a continuously exposed application metric with verified fixed application selectors:

```text
namespace: label_values(<metric>{<fixed-app-selectors>}, kubernetes_namespace)
pod:       label_values(<metric>{<fixed-app-selectors>,kubernetes_namespace="$namespace"}, kubernetes_pod_name)
```

Prefer structured Prometheus label-value variable queries when the pinned Grafana/Grafonnet API supports them. `label_values(...)` is Grafana variable syntax, not standalone PromQL.

### Dashboard V2 Prometheus query payload

A Dashboard V2 `QueryVariable` contains a generic `DataQuery`, but its inner `spec` is datasource-plugin-specific. Do not reuse the Prometheus panel-query `expr` field for a variable query.

For the documented Grafana/Grafonnet v13 pin, a classic `label_values(...)` variable query uses:

```json
{
  "kind": "QueryVariable",
  "spec": {
    "query": {
      "kind": "DataQuery",
      "group": "prometheus",
      "datasource": {
        "name": "<datasource-variable-reference>"
      },
      "spec": {
        "qryType": 1,
        "query": "label_values(<metric>{<selectors>}, <label>)",
        "refId": "PrometheusVariableQueryEditor-VariableQuery"
      }
    }
  }
}
```

An `expr`-only variable payload may satisfy the generic Dashboard V2 structure while Grafana's Prometheus variable editor displays an empty query. Validate the plugin-specific payload, not only the outer schema.

For another target or plugin pin, inspect a locally created/exported query variable or the pinned datasource plugin model before changing these fields.

Request/event counters may not exist before first activity. Where required, union discovery with application-scoped `up` or verified KSM membership.

## Matchers

Single-value variable:

```promql
label="$namespace"
```

Multi-value or All variable:

```promql
label=~"${pod:regex}"
```

Grafana's `regex` interpolation escapes individual values and joins multi-selections as a regex expression. Use `=~`, not `=`, for multi/All variables.

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

Enable All only with a bounded meaning. With an empty custom All value, Grafana expands the scoped option values rather than substituting a custom wildcard. Keep the option query application-scoped.

Do not replace the empty custom All value with `.*` unless every consumer independently enforces application scope.

## Refresh

Refresh on dashboard load for time-independent option queries. Use time-range refresh only when the option query actually depends on dashboard time.

Child variable queries must explicitly reference their parent variables so Grafana can refresh them when parent selections change.
