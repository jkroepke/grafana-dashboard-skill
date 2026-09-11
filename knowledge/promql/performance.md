# PromQL dashboard performance

Interactive dashboard queries should be bounded in both time and series cardinality.

## Prefer

- fixed application selectors before expensive operations
- bounded dimensions such as status class, method, route template, queue, topic, container
- aggregation that removes unnecessary labels after reset-sensitive functions
- recording rules already present and semantically verified in the environment

## Existing recording rules

Prefer an existing recording-rule output only when approved evidence establishes
that its population, grouping labels, window, unit, and meaning answer the
planned question.

Treat the recording-rule output according to its approved output type and
semantics, not according to the source metric name or the recording-rule name.
For example, a rule that already records requests/second is a derived rate; do
not apply `rate()` to it again merely because it originated from a counter.

If a recording rule removed a dimension required by the planned result identity,
it is not an equivalent replacement for the raw metric. Use the source that can
still answer the question.

Do not introduce a new recording rule as part of dashboard generation. Use only
rules already present or verified in the environment.

## Avoid

- raw paths, URLs, IDs, messages, trace IDs, user IDs
- datasource-wide regexes when application identity is available
- unnecessary subqueries
- repeated label regex rewriting on high-cardinality inputs
- many-to-many joins
- `.*` workload selectors without independent application scope
- long-range high-resolution queries when a lower resolution answers the panel question
- recomputing the same expensive semantic result independently in many panels

## Review

For an expensive query inspect:

- selected time range
- evaluation step
- range-selector and subquery windows
- input series count
- output series count
- labels retained through joins/aggregation
- whether regex rewriting runs before cardinality reduction
- whether the same result is recomputed independently in many panels
- whether an equivalent verified recording-rule output already exists

A query being syntactically valid or returning quickly for one narrow test range
does not prove it is suitable for the dashboard's allowed time range and
variable cardinality.
