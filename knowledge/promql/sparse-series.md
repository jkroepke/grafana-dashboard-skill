# Sparse and late-created Prometheus series

## Counter created on first event

Some applications do not expose a counter until an event occurs. The first scrape may therefore observe a non-zero value without an earlier zero sample.

Example:

```text
12:00  no series
12:03  application creates app_events_total=5
12:04  scrape observes 5
```

A plain expression:

```promql
increase(app_events_total[5m])
```

cannot derive the initial five events from a missing earlier sample.

## Environment pattern: include initial observed value

When the metric lifecycle contract establishes that a newly appearing counter is created by events in the evaluated range, this pattern can include the first observed value:

```promql
(
  increase(app_events_total[5m])
  +
  (
    min_over_time(app_events_total[5m])
    unless
    app_events_total offset 5m
  )
)
or
increase(app_events_total[5m])
```

For a dashboard-selected period, substitute the intended duration consistently when the datasource/Grafana version supports it, for example `$__range`.

### Semantics

- `increase(...)` handles normal observed counter increases and resets.
- `min_over_time(...) unless metric offset <range>` contributes an observed starting value only for a label set that is present now/in-range but absent at the offset point.
- the final `or increase(...)` preserves normal results for label sets where the additive branch does not produce a series

This is a semantic workaround, not a generic replacement for `increase()`.

### Required assumptions

Use only when all relevant assumptions are established:

- the series is created because events occurred after it was previously absent
- the first exposed value represents events that should belong to the evaluated period
- an already-existing persisted/backfilled counter cannot suddenly appear with old history
- the offset-point absence is meaningful and not caused by a scrape gap or target outage

### Limitations

Prometheus cannot determine when events represented by the first observed value actually occurred before the first scrape.

A reset inside the same range can make `min_over_time()` smaller than the first observed value, including zero. Validate reset behavior against the application's lifecycle before using this pattern for exact totals.

Series disappearance caused by staleness, scrape failure, target replacement, retention, or selector changes can also make offset-based absence ambiguous.

Do not describe the result as mathematically exact when these cases are possible.

## Zero-valued output

Set operators preserve label-set presence, not arbitrary zero filling. Verify that a query still returns expected zero-valued series when no increase occurs.

Do not add blanket `or vector(0)`: it loses workload labels and can turn missing instrumentation into an apparent healthy zero.

## Discovery

Do not use activity-dependent request/event counters as the only source for dashboard pod variables when pods with no activity must remain selectable.

Prefer a continuously exposed application metric, application-scoped `up`, or verified KSM membership.
