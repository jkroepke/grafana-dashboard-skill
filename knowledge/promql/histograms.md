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

## Native histogram quantile

Use native-histogram expressions only when native samples are verified in the datasource:

```promql
histogram_quantile(
  0.95,
  sum(
    rate(http_request_duration_seconds{...}[$__rate_interval])
  )
)
```

Do not invent `_bucket` series for native histograms. A text exposition dump alone may not establish the representation stored by Prometheus.

## Mean

Classic histogram mean:

```promql
sum(rate(h_sum{...}[$__rate_interval]))
/
sum(rate(h_count{...}[$__rate_interval]))
```

Require a positive matching denominator. Preserve no-data when the denominator is absent/zero.

## Summaries

Client-side summary quantiles cannot be meaningfully averaged or combined into an application-wide quantile. Display them per original population/instance or use count/sum when those answer the question.

## Heatmaps

A heatmap requires a correct time-varying distribution representation. Do not feed cumulative raw counter values into a heatmap or histogram visualization without the required rate/delta transformation.
