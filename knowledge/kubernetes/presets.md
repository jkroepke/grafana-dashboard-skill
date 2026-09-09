# Kubernetes and Istio workload presets

The coordinator's checked dispatch helper is the fixed, offline inventory catalogue for
workload-scoped Kubernetes and Istio candidates. It does not read Prometheus,
inspect a cluster, or receive namespace values. `application-metrics` remains
the sole owner of the exact target namespace set; the Kubernetes stage copies
that validated scope reference unchanged into its artifact.

The catalogue is deliberately a candidate list, not a promise that every
exporter, kube-state-metrics version, or Istio deployment emits every family.
`DOCUMENTED` records and their `documented_labels` are not observed evidence.
The metrics reviewer must verify both family and selected labels in the target
before approving a metric for `PLAN`. Istio `Telemetry.metricsOverrides` can
change the emitted metric and label set.

## kubernetes-workload

This profile is distilled from the workload/pod and namespace views: resource
use and configured capacity, readiness and lifecycle, then per-container
diagnostics. It intentionally excludes cluster-total capacity and node-wide
metrics because this skill only works from the application-derived namespace
scope.

| ID | Metric family | Candidate panel purpose |
| --- | --- | --- |
| K001 | `container_cpu_usage_seconds_total` | CPU use by container |
| K002 | `container_memory_working_set_bytes` | Memory working set by container |
| K003 | `container_cpu_cfs_throttled_seconds_total` | CPU throttling trend |
| K004 | `kube_pod_container_resource_requests` | Configured requests comparison |
| K005 | `kube_pod_container_resource_limits` | Configured limits comparison |
| K006 | `kube_pod_status_ready` | Readiness state |
| K007 | `kube_pod_container_status_restarts_total` | Restart trend |
| K008 | `container_oom_events_total` | OOM event trend |
| K009 | `kube_pod_status_phase` | Pod phase state |
| K010 | `kube_pod_status_scheduled` | Scheduling state |
| K011 | `kube_pod_container_state_started` | Start-time capability |
| K012 | `kube_pod_container_status_waiting_reason` | Container waiting diagnostics |
| K013 | `kube_pod_status_reason` | Pod reason diagnostics |

`dashboard-architect` may use a compact Resource and availability group
(K001–K007), an optional Lifecycle group (K008–K011), and a label-rich
Diagnostics group (K012–K013). It must omit incomplete comparisons, such as
usage versus an unverified resource dimension or a missing limit.

## istio-workload

The Istio standard HTTP/gRPC and TCP metric families provide a separate,
optional service-mesh group. Scope each approved question through the verified
source or destination workload namespace selector; do not apply Kubernetes
`pod` selectors to Istio traffic.

| ID | Metric family | Candidate panel purpose |
| --- | --- | --- |
| I001 | `istio_requests_total` | Request rate and errors |
| I002 | `istio_request_duration_milliseconds` | Latency percentile |
| I003 | `istio_request_bytes` | Request throughput |
| I004 | `istio_response_bytes` | Response throughput |
| I005 | `istio_request_messages_total` | gRPC request message rate |
| I006 | `istio_response_messages_total` | gRPC response message rate |
| I007 | `istio_tcp_sent_bytes_total` | TCP sent throughput |
| I008 | `istio_tcp_received_bytes_total` | TCP received throughput |
| I009 | `istio_tcp_connections_opened_total` | TCP connection-open rate |
| I010 | `istio_tcp_connections_closed_total` | TCP connection-close rate |

`dashboard-architect` may plan an optional Istio group only when the reviewer
has approved enough compatible candidates: requests plus duration for HTTP,
or the relevant TCP counters for TCP. It should preserve source/destination
direction and reporter semantics rather than merging them into an unexplained
total.

## Sources and boundaries

The Kubernetes profile follows the panel families in the referenced
[pod view](https://github.com/dotdc/grafana-dashboards-kubernetes/blob/master/dashboards/k8s-views-pods.json)
and [namespace view](https://github.com/dotdc/grafana-dashboards-kubernetes/blob/master/dashboards/k8s-views-namespaces.json),
without importing their classic dashboard JSON or cluster-wide assumptions.
The Istio profile uses the documented standard metric families and labels in
[Istio Standard Metrics](https://istio.io/latest/docs/reference/config/metrics/).
It is compatible in intent with Grafana's
[workload](https://grafana.com/grafana/dashboards/7630-istio-workload-dashboard/),
[service](https://grafana.com/grafana/dashboards/7636-istio-service-dashboard/),
and [mesh](https://grafana.com/grafana/dashboards/7639-istio-mesh-dashboard/)
dashboards, but is not a copy of them.
