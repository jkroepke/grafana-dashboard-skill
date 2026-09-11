# PromQL aggregation

## Decide result identity first

Before aggregating, state the output identity labels. Use `by (...)` to keep
only the intended grouping labels, or `without (...)` only when the labels to
remove are the stable contract. Do not let accidental exporter labels define
the result shape.

`count(...)` counts input series, not real-world entities. Treat it as an
entity count only when approved evidence establishes one input series per
entity for the selected scope.

## Counters

Never sum raw counters and then apply a counter function. Apply the
reset-sensitive function per source series first, then aggregate:

```promql
sum by (namespace) (
  rate(requests_total{...}[$__rate_interval])
)
```

Read `counters.md` for the type and lifecycle requirements.

## Ratios: aggregate components, then divide

For a population ratio, aggregate numerator and denominator independently over
the same population and grouping, then divide:

```promql
sum by (namespace) (
  rate(request_errors_total{...}[$__rate_interval])
)
/
sum by (namespace) (
  rate(requests_total{...}[$__rate_interval])
)
```

Do not average per-series ratios unless the planned question explicitly asks
for an unweighted average of those entities. In general:

```promql
avg(error_rate / request_rate)
```

is not equivalent to the population error ratio.

The same warning applies to percentages and summary/histogram quantiles: do not
average derived values from different populations and call the result a global
population value.

## `topk` / `bottomk`

In a range query, `topk(k, expr)` or `bottomk(k, expr)` is evaluated separately
at every step. The union of returned series over the dashboard range can
therefore contain more than `k` unique series.

Use an instant query when the question is "top k now" or "top k at dashboard
end". Do not promise a stable set of `k` time-series lines from a range query
without an explicit ranking strategy.

## Deduplication is semantic

Do not use `sum`, `max`, `min`, or `avg` merely to silence duplicate-series or
many-to-many errors. First identify why multiple observations share the same
logical identity, then apply only the aggregation justified by that source
semantics. Read `joins.md` for vector matching.
