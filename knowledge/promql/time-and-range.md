# PromQL time, ranges, and historical comparisons

## Query mode is not a range selector

A Prometheus range query evaluates an instant PromQL expression repeatedly at
multiple steps. It does not automatically turn every selector into a range
vector.

Keep these separate:

- query mode: one evaluation (`INSTANT`) versus repeated evaluations (`RANGE`)
- range selector: `metric[5m]`, which supplies samples to a range function
- subquery: `(expr)[1h:5m]`, which supplies repeated evaluations of a derived expression

Choose each from the planned question; do not add brackets merely because the
panel is a time series.

## Grafana windows

For a dashboard counter trend, prefer Grafana's `$__rate_interval` when the
query uses `rate()` or `irate()` and the datasource supports it:

```promql
rate(requests_total{...}[$__rate_interval])
```

Use `$__range` only when the calculation intentionally spans the full selected
dashboard period, for example an instant selected-period total:

```promql
increase(requests_total{...}[$__range])
```

Do not replace `$__rate_interval` with `$__interval`. Panel resolution and a
safe counter lookback window are different concerns.

## `_over_time` functions

Use `_over_time` functions when the question is about samples of one series
over a defined window. Common gauge shapes are:

```promql
avg_over_time(queue_depth{...}[1h])
max_over_time(queue_depth{...}[1h])
min_over_time(queue_depth{...}[1h])
```

Do not use `avg_over_time(raw_counter[...])` as a throughput calculation. For a
counter, first use counter semantics such as `rate()` or `increase()` when the
approved type permits it.

`delta()` and `deriv()` are gauge operations for this workflow. Do not use them
as substitutes for missing counter type evidence or reset semantics.

## Subqueries

Use a subquery only when an outer range function must consume a derived instant
expression over time. Shape:

```promql
avg_over_time(
  (sum by (namespace) (rate(requests_total{...}[5m])))[1h:5m]
)
```

A subquery repeats the inner expression across its own range and resolution.
Before using one in an interactive panel, check `performance.md` for query cost
and whether a semantically equivalent verified recording-rule output already
exists. Do not introduce a new recording rule from this workflow.

## `offset`

Use `offset` for an explicit historical comparison of the same selector, for
example one week earlier:

```promql
rate(requests_total{...}[5m] offset 1w)
```

The comparison is valid only while the selected labels still represent the
same logical population. Pod replacement, label changes, retention, scrape
gaps, or changed instrumentation can make historical absence ambiguous.

Do not describe `offset 1w` as "previous dashboard period" unless the planned
question actually defines that exact duration.

## `@`

Use `@` only when the question requires a selector evaluated at a fixed point,
for example `@ start()` or `@ end()` in a range query. It freezes selector
evaluation time; it is not a normal trend-query requirement.

Require the pinned Prometheus-compatible datasource to support the intended `@`
form and validate the actual query. Do not add `@` merely to make a result look
stable.
