# Grafana process-start and restart annotations

When a verified process/application start timestamp metric exists, prefer an event annotation based on that timestamp.

Confirm metric unit and meaning from local metadata. Do not use an unrelated timestamp.

## Preferred behavior

Where supported by the pinned Grafana/Prometheus plugin, map the metric value (Unix seconds) to event time.

- query across dashboard period
- retain pod/process identity
- verify repeated scrapes of the same timestamp produce one event marker
- verify seconds/milliseconds conversion
- use `$datasource` and the same application/cluster selectors as panels

Label this event `Process started`. A process-start timestamp does not prove container restart, pod replacement, or rollout cause.

## Fallback: changes within same series

If timestamp-value mapping is unavailable:

```promql
changes(process_start_time_seconds{
  kubernetes_namespace="$namespace",
  kubernetes_pod_name=~"${pod:regex}"
}[<verified-short-window>]) > 0
```

Add fixed application/cluster selectors.

This detects value changes only within the same complete label set. It does not detect a replacement pod/new label set.

Label the fallback `Observed process restart` and document coverage.

Choose the window from scrape interval and query step. Rolling windows can create duplicate markers.

## Validation cases

When history exists, test:

- same-label process restart
- replacement pod/new label set
- repeated unchanged timestamp scrapes
- dashboard range filtering
- selected pod and All behavior

Do not claim starts that monitoring never observed or multiple starts between scrapes.
