# PromQL histograms and summaries

## Classic histogram quantile

Apply rate to buckets before aggregation and retain `le` plus intended grouping labels:

```promql
histogram_quantile(
  0.95,
  sum by (le) (
    rate(http_request_duration_seconds_bucket{...}[$__rate_interval])
  )
)
```

For per-route quantiles:

```promql
histogram_quantile(
  0.95,
  sum by (le, route) (
    rate(http_request_duration_seconds_bucket{...}[$__rate_interval])
  )
)
```

Only keep bounded route templates, never unbounded raw paths.

A quantile answers for the estimated value at a percentile. It does not answer
what fraction of observations is below a fixed SLO threshold. For a fixed
threshold SLI, use the appropriate cumulative bucket and `_count` pattern in
`slis.md` when the required bucket boundary exists.

## Native histograms

Use native-histogram expressions only when native histogram samples are verified in the local datasource and the pinned Prometheus version supports the required functions.

Do not infer native-histogram ingestion or function availability from metric names, a text exposition dump, or general documentation. Check local metadata/version and validate the actual query.

Quantile when supported:

```promql
histogram_quantile(
  0.95,
  sum(
    rate(http_request_duration_seconds{...}[$__rate_interval])
  )
)
```

For grouped native-histogram quantiles, keep the intended grouping labels in `sum by (...)`; no `le` label is required.

Mean when `histogram_avg()` is available locally:

```promql
histogram_avg(
  sum(rate(http_request_duration_seconds{...}[$__rate_interval]))
)
```

Equivalent form when `histogram_sum()` and `histogram_count()` are available locally:

```promql
histogram_sum(sum(rate(http_request_duration_seconds{...}[$__rate_interval])))
/
histogram_count(sum(rate(http_request_duration_seconds{...}[$__rate_interval])))
```

Do not invent `_bucket` series for native histograms.

If a query returns warnings or omits series because of mixed sample representations or unsupported behavior, treat validation as failed until understood.

## Classic histogram mean

```promql
sum(rate(h_sum{...}[$__rate_interval]))
/
sum(rate(h_count{...}[$__rate_interval]))
```

Require a positive matching denominator. Preserve no-data when the denominator is absent/zero.

## Summaries

Client-side summary quantiles cannot be meaningfully averaged or combined into an application-wide quantile. Display them per original population/instance or use count/sum when those answer the question.

Do not average per-instance summary quantiles to create a global p95/p99.

## Heatmaps

A heatmap requires a correct time-varying distribution representation. Do not feed cumulative raw counter values into a heatmap or histogram visualization without the required rate/delta transformation.
