# PromQL counters

## Rate before aggregation

Apply counter functions before aggregation so resets are detected per series:

```promql
sum by (code) (
  rate(http_requests_total{...}[$__rate_interval])
)
```

Do not aggregate raw counters first and then apply `rate()` unless the input is a recording rule with established counter-reset semantics.

## Rate versus selected-period total

Use rate for a trend/current throughput:

```promql
rate(counter[$__rate_interval])
```

Use increase for a count over an intentional period:

```promql
increase(counter[$__range])
```

For selected-period totals, normally use an instant query evaluated at the dashboard end time. A range query of `increase(counter[$__range])` produces a rolling total at each evaluation point, which answers a different question.

## Sample requirement and extrapolation

`rate()` and `increase()` need at least two samples in the selected range to calculate a change. A newly observed series with only one sample produces no result for the increase calculation.

Both functions infer counter change from samples and extrapolate to range boundaries. They do not observe events directly and can return non-integer increases for integer counters.

Do not claim exact event counts when scrape gaps, sparse samples, or series lifecycle make that unknowable.

## Counter reset

A decrease within one time series is interpreted by counter functions as a reset. This requires the same complete label set to continue across samples.

A replacement pod that changes labels creates a new series; it is not a reset of the old series.

## First observed sample

A counter first observed at a non-zero value has no earlier sample from which `increase()` can infer those initial events. Do not silently add the initial value unless metric lifecycle semantics justify doing so.

For the environment-specific late-created-counter pattern, read `sparse-series.md`.

## Ratios

Build numerator and denominator over the same population and grouping.

Do not clamp a missing/zero denominator to an arbitrary positive value. Preserve no-data when the ratio is undefined.
