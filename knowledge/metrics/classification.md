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

## General rule

Use `BUSINESS` only for a measured domain outcome, workload activity, or
application-specific state whose semantics are supported by observed evidence.
Use `PROCESS` for framework, runtime, garbage-collection, client-library,
build, and static identity instrumentation. When evidence cannot distinguish
the two, retain `NEEDS_AI` rather than deciding from a metric name.
