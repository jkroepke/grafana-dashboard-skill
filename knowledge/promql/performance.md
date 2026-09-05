# PromQL dashboard performance

Interactive dashboard queries should be bounded in both time and series cardinality.

## Prefer

- fixed application selectors before expensive operations
- bounded dimensions such as status class, method, route template, queue, topic, container
- aggregation that removes unnecessary labels after reset-sensitive functions
- recording rules already present and semantically verified in the environment

## Avoid

- raw paths, URLs, IDs, messages, trace IDs, user IDs
- datasource-wide regexes when application identity is available
- unnecessary subqueries
- repeated label regex rewriting on high-cardinality inputs
- many-to-many joins
- `.*` workload selectors without independent application scope
- long-range high-resolution queries when a lower resolution answers the panel question

## Review

For an expensive query inspect:

- selected time range
- evaluation step
- input series count
- output series count
- labels retained through joins/aggregation
- whether the same result is recomputed independently in many panels

Do not introduce a new recording rule as part of dashboard generation. Use only rules already present or verified in the environment.
