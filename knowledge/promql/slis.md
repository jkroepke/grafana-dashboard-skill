# PromQL SLI and utilization patterns

## Define the population before the formula

Before building an SLI or ratio, establish from approved evidence:

- numerator population
- denominator population
- grouping/result identity
- time window
- units
- missing/zero denominator behavior

The numerator and denominator must describe the same logical population unless
the planned question explicitly defines otherwise.

## Error or failure ratio

For counter-backed request populations, aggregate components separately and
then divide:

```promql
sum by (namespace) (
  rate(request_errors_total{...}[$__rate_interval])
)
/
sum by (namespace) (
  rate(requests_total{...}[$__rate_interval])
)
```

Do not average per-pod error percentages to produce a namespace error ratio.
Do not clamp an absent or zero denominator to a positive value; preserve the
undefined/no-data state.

A success ratio can be computed from explicitly verified success and total
populations. `1 - error_ratio` is valid only when the error population is known
to be the exact complement of success within the same denominator.

## `up` is scrape health

Prometheus `up` answers whether the scrape succeeded for a target. It is not,
by itself, an application availability SLI, HTTP success ratio, readiness
signal, or user-visible service health measure.

Use `up` as availability only when the planned question explicitly asks about
Prometheus target scrape availability.

## Latency threshold SLI from a classic histogram

When the question is "what fraction of observations completed at or below a
latency threshold?", a cumulative classic histogram bucket can be the numerator
and `_count` the denominator:

```promql
sum by (namespace) (
  rate(request_duration_seconds_bucket{le="0.3", ...}[$__rate_interval])
)
/
sum by (namespace) (
  rate(request_duration_seconds_count{...}[$__rate_interval])
)
```

Use only an actually present bucket boundary whose unit matches the SLO
threshold. If the exact threshold is not represented by a classic bucket, the
exact fraction cannot be recovered from the buckets; any approximation must be
explicitly allowed by the plan.

`histogram_quantile(0.95, ...)` answers for the latency value at an estimated
quantile. It does not directly answer the fraction of observations below a
fixed latency threshold. Do not interchange those questions.

Read `histograms.md` for classic/native histogram semantics.

## Utilization and saturation ratios

For a usage/capacity ratio, verify both sides have compatible units and the same
result identity before division:

```promql
usage
/
on (namespace, pod)
capacity
```

Use `group_left`/`group_right` only when the verified source cardinality
requires it; read `joins.md`.

Do not assume Kubernetes request, limit, allocatable, quota, or physical
capacity are interchangeable denominators. Select the denominator required by
the planned question.

Do not clamp ratios to `0..1` merely for display. Values above one can be
semantically meaningful for some denominators; clipping destroys evidence.

## Error-budget burn rate

When an SLO target is explicitly supplied and the error ratio uses the same SLI
population, burn rate is:

```text
error_ratio / (1 - slo_target)
```

Do not invent a default SLO target or alerting window. Multi-window burn-rate
thresholds are policy inputs, not generic PromQL defaults.
