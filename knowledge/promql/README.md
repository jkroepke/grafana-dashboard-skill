# PromQL knowledge router

Read this file for every PromQL build or review task. Then read only the topic
files whose triggers match the query. Do not load the whole directory.

The approved metrics contract overrides every example in this directory.
Example metric and label names are query shapes only; they are never evidence
that a metric, type, label, or dimension exists.

| Trigger in the planned query | Read |
| --- | --- |
| counter, `rate`, `irate`, `increase`, `resets` | `counters.md` |
| `sum`, `avg`, `count`, `topk`, ratio aggregation | `aggregation.md` |
| range selector, query mode, `_over_time`, subquery, `offset`, `@` | `time-and-range.md` |
| classic/native histogram, quantile, summary, heatmap | `histograms.md` |
| availability, error/success ratio, latency SLI, saturation, burn rate | `slis.md` |
| binary vector matching, `on`, `ignoring`, `group_left`, `group_right` | `joins.md` |
| Kubernetes ownership or resource joins | `kubernetes-joins.md` |
| absent, stale, zero, set operators, comparison `bool` | `missing-series.md` |
| late-created or sparse event series | `sparse-series.md` |
| expensive query, high cardinality, recording-rule reuse | `performance.md` |
| Prometheus reader/probe request shape | `reader-requests.md` |

For a `CUSTOM` query, identify every applicable trigger and read those files
before authoring or reviewing the expression. `CUSTOM` relaxes the template
allowlist, not metric evidence, type evidence, identity, or no-data rules.

When required semantics are not established by approved evidence, do not invent
a conventional PromQL pattern. Return the workflow's evidence blocker instead.
