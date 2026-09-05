# Kubernetes dashboard metric contracts

Use only metric families available locally or documented by pinned/local sources. Mark availability unverified until observed or queried.

## Common signals

| Signal | Typical source/calculation | Unit/meaning |
| --- | --- | --- |
| CPU usage | `rate(container_cpu_usage_seconds_total[$__rate_interval])` | CPU cores |
| Memory | `container_memory_working_set_bytes` | bytes; working set, not exact OOM headroom |
| Container requests | `kube_pod_container_resource_requests` | CPU core or memory byte according to resource/unit labels |
| Container limits | `kube_pod_container_resource_limits` | CPU core or memory byte according to resource/unit labels |
| Pod scheduling requests | `kube_pod_resource_requests` from kube-scheduler when exposed | effective pod-level scheduling request; verify resource/unit labels |
| Pod scheduling limits | `kube_pod_resource_limits` from kube-scheduler when exposed | effective pod-level scheduling limit; verify resource/unit labels |
| Readiness | `kube_pod_status_ready{condition="true"}` | ready/not-ready state |
| Restarts | `increase(kube_pod_container_status_restarts_total[<window>])` | restart count over stated window |
| Container start time | `kube_pod_container_state_started` when exposed | Unix timestamp gauge; potential annotation source |
| CPU throttling | throttled periods / total periods | fraction of periods throttled, not CPU time lost |
| OOM events | `increase(container_oom_events_total[<window>])` when collected | observed events |
| Replicas | workload-kind KSM metrics | desired/ready/available workload state |

Verify exact labels and metric versions in the local datasource.

When kube-scheduler `kube_pod_resource_requests` or `kube_pod_resource_limits` are locally exposed, prefer them for pod-level scheduling-resource views. Keep KSM container resource metrics for per-container usage/request/limit comparisons. Do not assume scheduler metrics exist merely because KSM container metrics are present.

## Labels

Application stored scrape labels in this target environment:

```text
kubernetes_namespace
kubernetes_pod_name
```

Native KSM/cAdvisor workload labels normally use:

```text
namespace
pod
container
```

Do not assume they were relabeled to application names. Likewise, labels attached by the scrape pipeline may be absent from a raw exporter exposition.

## Container calculations

Exclude:

```promql
container!="",container!="POD"
```

Prefer a verified application container set. If only total pod scope is known, include regular sidecars and label the panel as total pod usage.

For usage/request/limit comparisons:

1. select identical containers on numerator and denominator
2. retain `(namespace,pod,container)` and cluster identity until matching is resolved
3. inspect duplicate scrape paths/exporter replicas
4. require a positive denominator for every included container for whole-population ratios
5. show usage and configured resources separately when denominator coverage is incomplete

A missing/zero limit is not numeric unlimited capacity.

Usage/request may exceed 100% because requests are scheduling inputs, not ceilings.

## Workload state

Deployment/StatefulSet/DaemonSet replica metrics require the verified workload kind/name. Prefer owner relationships over guessed pod-name regexes.

Workload-wide desired replicas do not change when the dashboard selects a subset of pods; label such panels as workload-wide.

## Start timestamps

`kube_pod_container_state_started`, when available, represents the container start time as a Unix timestamp gauge. Restrict it to the verified application container population before using it for restart annotation logic.

Grafana Prometheus annotations use returned sample timestamps as marker time, not the gauge value. Read `knowledge/grafana/annotations.md` before building an annotation from this metric.

## Scrape availability

Use `up` only when selectors are verified to identify the intended application target. Exporter scrape labels can identify the exporter rather than workloads represented by its metrics.
