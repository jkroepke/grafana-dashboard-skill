# Opaque Prometheus reader requests

Use this only after a role has identified the metric/selector it needs. Do not
inspect `.env`, construct a URL, select a datasource UID, or invoke an HTTP
client directly.

The request file is a JSON object with exactly these two fields:

```json
{
  "operation": "query",
  "params": {
    "query": "up"
  }
}
```

Run the workspace-local wrapper as:

```text
./prometheus-reader <request-file> <response-file>
```

It chooses the configured target/datasource and writes the raw response only to
the response file. It never accepts an endpoint, credentials, headers, or a
datasource UID in the request file.

Allowed operations and required parameters:

| Operation | Required `params` | Purpose |
| --- | --- | --- |
| `query` | `query` | instant PromQL query; `time` is optional |
| `query_range` | `query`, `start`, `end`, `step` | range PromQL query |
| `series` | `match[]` | stored-series discovery |
| `labels` | none | available label names |
| `metadata` | none | metric metadata |
| `label_values` | `label` | values for one label |

All parameter values are strings, except a repeated parameter such as
`match[]`, which may be an array of strings. For example:

```json
{
  "operation": "series",
  "params": {
    "match[]": "<verified_metric>{<approved_selector>}"
  }
}
```

`label_values` is an API operation. It is not the Grafana dashboard expression
`label_values(metric, label)`; the latter belongs only in a variable-query
record.

## Application deployment discovery

The application-metrics analyst must run `./metrics-discovery` after it has a
local snapshot. This deterministic helper submits a narrow `series` request for
every observed family with no guessed namespace selector, retains the raw
request/response pairs, and writes `evidence/metric-discovery/summary.json`:

```json
{
  "operation": "series",
  "params": {
    "match[]": "<observed_metric_family>"
  }
}
```

The bounded summary records series count, namespace candidates, the candidate
namespace-label keys (`namespace` and `kubernetes_namespace`), and an
empty/API-error result for every family. Each request and response has the
fixed path `requests/<snapshot-id>.json` and `responses/<snapshot-id>.json`;
inspect the response only when its compact summary entry needs follow-up. The
helper probes at most 512 snapshot families and fails closed above that limit.
On a resumed application stage it verifies that this evidence matches the
current snapshot IDs/families and reuses it; it neither overwrites it nor sends
the requests again.
It does not decide which series belong to the target application. A returned
namespace is in scope only when the returned series is tied to the target
application by a target-specific family or verified identity labels. Do not
treat a shared framework metric name by itself as proof, and never use a
cluster-wide Kubernetes metric, workload-name guess, or pod-name pattern as a
substitute.
