# PromQL counters

## Type evidence overrides the name

Use the type recorded in the approved metrics contract. Names are conventions,
not evidence. If the exporter says:

```text
# TYPE http_requests_total gauge
http_requests_total 42
```

then `http_requests_total` is a gauge for this workflow. The `_total` suffix,
HELP text, a numeric value, or samples that happen to increase do not authorize
reclassifying it as a counter.

Do not apply `rate()`, `irate()`, `increase()`, or `resets()` to that series.
Do not use `delta()`, `deriv()`, or offset subtraction as a hidden workaround
for intended counter behavior: those operations do not supply counter reset and
lifecycle semantics. Record `TYPE_SEMANTICS_CONFLICT` and route the application
instrumentation defect back to the coordinator. Fixing the exporter is the
normal resolution. The metric may still be used as a gauge only when its actual
gauge meaning supports the planned question.

If `TYPE` is absent, keep the type `unknown`; a counter-like name does not fill
the evidence gap.

## Rate before aggregation

Apply counter functions before aggregation so resets are detected per series:

```promql
sum by (code) (
  rate(http_requests_total{...}[$__rate_interval])
)
```

Do not aggregate raw counters first and then apply `rate()` unless the input is a recording rule with established counter-reset semantics.

## `rate` versus `irate`

Use `rate()` as the default for dashboard trends and alert-like state. It uses
all samples in the lookback window and is less sensitive to scrape jitter and
single-sample spikes.

Use `irate()` only when the planned question explicitly needs a very responsive
view of a volatile counter. It is based on the last two samples in the range and
can be noisy.

Do not use `irate()` for selected-period totals. Do not prefer it merely because
it appears more "real time". If aggregation is required, apply `irate()` to the
individual counter series before aggregation for the same reset-detection reason
as `rate()`.

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

`rate()`, `irate()`, and `increase()` need at least two samples in the selected
range to calculate a change. A newly observed series with only one sample
produces no result for the change calculation.

`rate()` and `increase()` infer counter change from samples and extrapolate to
range boundaries. They do not observe events directly and can return
non-integer increases for integer counters.

Do not claim exact event counts when scrape gaps, sparse samples, or series lifecycle make that unknowable.

## Counter reset

A decrease within one time series is interpreted by counter functions as a reset. This requires the same complete label set to continue across samples.

A replacement pod that changes labels creates a new series; it is not a reset of the old series.

## First observed sample

A counter first observed at a non-zero value has no earlier sample from which `increase()` can infer those initial events. Do not silently add the initial value unless metric lifecycle semantics justify doing so.

For the environment-specific late-created-counter pattern, read `sparse-series.md`.

## Ratios

Build numerator and denominator over the same population and grouping. Aggregate
the components first and divide the aggregated components; read
`aggregation.md` and `slis.md`.

Do not clamp a missing/zero denominator to an arbitrary positive value. Preserve no-data when the ratio is undefined.
