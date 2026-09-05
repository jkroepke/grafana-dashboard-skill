# Missing, zero, and stale series

Treat these states separately:

- observed numeric zero
- series absent because no event/label value was created
- series stale after target disappearance
- scrape failure
- instrumentation missing
- selector does not match
- workload no longer exists

PromQL set operators operate on label-set presence.

## `or`

Use `or` to union label sets or provide a semantically valid fallback with compatible labels.

Do not use `or vector(0)` as a generic no-data fix. A label-less zero can hide missing instrumentation and does not preserve application identity.

## `unless`

`A unless B` returns label sets from `A` that do not have a matching label set in `B`. Use it for presence logic only when matching identity is deliberate.

## `absent()` / `absent_over_time()`

Use absence functions for detecting missing series, not for inventing a numeric value for the original metric.

Ensure selectors identify the intended application; datasource-wide absence checks can be misleading.

## `present_over_time()`

Use `present_over_time(metric[window])` when the question is whether each matching label set had at least one sample in the window. It returns presence information for the original label sets; it does not prove successful scraping for every point in the window and is not a generic zero-fill mechanism.

## Staleness

A series that stops being scraped is not equivalent to a zero. Preserve this distinction in dashboard queries and panels.

## Error-rate fill

Filling a missing error series with zero is valid only when instrumentation semantics establish that absence means no errors and a matching traffic population exists. Preserve the same identity labels.

## Health

Never map missing data to healthy state by default.
