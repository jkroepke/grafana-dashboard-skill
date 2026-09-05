# Grafana Prometheus process-start and restart annotations

Use a verified process/container start timestamp metric when available, such as application `process_start_time_seconds` or KSM `kube_pod_container_state_started`.

Confirm metric type, unit, labels, and meaning from local metadata or live data. Do not use an unrelated timestamp metric.

## Prometheus annotation time semantics

Grafana executes Prometheus annotation expressions as range queries over the dashboard time range.

Every returned datapoint becomes an annotation marker. The marker time is the returned sample timestamp. The numeric metric value is not used as the annotation event timestamp.

Therefore this is wrong for a continuously scraped timestamp gauge:

```promql
process_start_time_seconds{...}
```

It returns a point at every evaluation step and floods the dashboard. A Unix timestamp stored in the sample value does not move those markers to that Unix timestamp.

## Same-label restart observation

For a start timestamp gauge that changes when the process restarts while the complete label set stays the same, use an event-like expression:

```promql
changes(process_start_time_seconds{
  kubernetes_namespace="$namespace",
  kubernetes_pod_name=~"${pod:regex}"
}[<window>]) > 0
```

Add verified fixed application/cluster selectors.

For KSM, use the native label contract and select only the relevant application container population:

```promql
changes(kube_pod_container_state_started{
  namespace="$namespace",
  pod=~"${pod:regex}",
  container=~"<verified-app-containers>"
}[<window>]) > 0
```

Choose `<window>` from the scrape interval and annotation query step so it contains enough samples to observe a change. Validate duplicate behavior. Overlapping windows can return the same change at multiple evaluation points; increase the annotation Min step or change the window when needed.

Label this `Observed process restart` or `Observed container restart`. The marker indicates when monitoring observed the change, not the exact Unix timestamp stored in the gauge.

## New pod or new label set

`changes()` needs multiple samples in the same series. It does not detect the initial appearance of a replacement pod/new label set.

Do not claim complete rollout or pod-replacement coverage from `changes()` alone.

A presence-edge expression may be used only when its semantics and duplicate behavior are validated against the local scrape interval and staleness behavior. Otherwise omit first-appearance markers rather than flooding the dashboard.

## Better event sources

Prefer a dedicated event-like metric or another datasource that carries the real event timestamp when one exists. Prometheus timestamp gauges are useful evidence but do not let the Prometheus annotation datasource remap sample values into event time.

## Validation

When history exists, test:

- same-label process/container restart
- replacement pod/new label set
- unchanged timestamp gauge
- annotation query step and lookback window
- duplicate markers
- dashboard range filtering
- selected pod and All behavior

Do not claim starts that monitoring never observed or multiple starts between scrapes.
