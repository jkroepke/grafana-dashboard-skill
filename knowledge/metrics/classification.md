# Application metric classification

Classification is not dashboard priority. It identifies whether a metric
describes a domain outcome (`BUSINESS`) or framework/runtime behavior
(`PROCESS`). The observed metric type, HELP text, members, and labels remain
facts; category does not change them.

## Pinned framework identity metrics

The following exact family is a framework/application identity capability, not
a domain business KPI:

| Exact family | Source | Category | Meaning |
| --- | --- | --- |
| `fastapi_app_info` | `APPLICATION` | `PROCESS` | static FastAPI application identity metadata |

The bounded conventional family pattern `<prefix>_build_info` is also
`PROCESS`: it records build identity/version metadata, not a business outcome.
For example, the local target exposes `grafana_build_info` as a constant gauge
with build/version labels. Preserve its observed labels/type; do not turn the
constant `1` into a health result.

Record it as `PROCESS` with its observed type and labels. It may support
inventory/deployment identity, but does not by itself prove traffic, errors,
readiness, health, or a business outcome. Do not promote it to `BUSINESS`, a
health signal, or a dashboard panel without separate target-specific evidence.

This is a deliberately narrow allowlist. A family merely ending in `_info`,
containing `app`, or having version-like labels is not automatically
classified. Keep every other unfamiliar information family `NEEDS_AI` until
its HELP and observed semantics establish its role.

## Pinned FastAPI server-workload metrics

The producer does not determine category. The default
`prometheus-fastapi-instrumentator` HTTP **server** metrics measure workload
arriving at the application, so they are `BUSINESS`, not `PROCESS`.

| Exact family | Required observed type | Required labels | Required HELP fragment |
| --- | --- | --- | --- |
| `http_requests_total` | `counter` | `handler`, `method`, `status` | `total number of requests` |
| `http_request_size_bytes` | `summary` | `handler` | `content length of incoming requests` |
| `http_response_size_bytes` | `summary` | `handler` | `content length of outgoing responses` |
| `http_request_duration_seconds` | `histogram` | `handler`, `method` | `latency with` |
| `http_request_duration_highr_seconds` | `histogram` | none | `latency with` |

The fact helper applies this only when every listed fingerprint field matches
the observed exposition. This follows the documented default families of
[`prometheus-fastapi-instrumentator`](https://github.com/trallnag/prometheus-fastapi-instrumentator).
It is a workload classification, not permission to infer counter semantics:
the declared type still controls query eligibility.

Do not extend this rule to a prefix/suffix pattern, a namespaced variant, an
outbound/client HTTP metric, or an arbitrary `http_*` family. Those require
observed HELP/labels and AI judgment. In particular, an
`http_requests_total` family declared as a `gauge` remains `NEEDS_AI` for
classification and a gauge for query validation.

## General rule

Use `BUSINESS` only for a measured domain outcome, workload activity, or
application-specific state whose semantics are supported by observed evidence.
Use `PROCESS` for framework/runtime self-observability, garbage collection,
client-library activity, build, and static identity instrumentation. A
framework's HTTP **server** metric is different: classify the thing observed
(incoming application workload), not the collector that emitted it. When
evidence cannot distinguish the two, retain `NEEDS_AI` rather than deciding
from a metric name.
