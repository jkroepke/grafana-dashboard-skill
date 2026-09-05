# Grafana panel selection

Choose visualization from the operational question and returned data shape.

| Question/data | Preferred visualization | Rules |
| --- | --- | --- |
| Numeric change over time | Time series | Default for rates, latency, queue depth, concurrency, CPU, memory, restart trends |
| Current or selected-period scalar | Stat | Use for a few important values; state the reduction/period |
| Value relative to meaningful capacity/range | Gauge or bar gauge | Require meaningful bounds; observed min/max are not capacity |
| Discrete state over time | State timeline | Readiness, leader state, lifecycle; preserve gaps as unknown |
| Every periodic discrete observation | Status history | Use when cells themselves matter rather than duration |
| Distribution over time | Heatmap | Requires correctly transformed histogram/distribution data |
| One-period distribution | Histogram | Requires raw observations or verified pre-bucketed frame, not cumulative counters |
| Bounded category comparison | Bar chart/bar gauge | Choose based on whether the result is categorical frame or labeled numeric series |
| Label-rich diagnostics | Table | Prefer for exact per-pod/container details, not primary overview |
| Mutually exclusive additive whole | Pie chart | Use sparingly; never for unrelated/overlapping values or trends |

## Rules

- Preserve time when temporal behavior aids diagnosis.
- Prefer built-in visualizations.
- Do not invent thresholds.
- Do not turn continuous signals into states without established boundaries.
- Do not reduce a time series to a Stat merely to simplify layout.
- Do not choose heatmap solely because the metric is a histogram.
- Use transformations only when the query result is semantically correct and the panel needs a different frame shape.
- Prefer a compact overview followed by investigative panels.
- Titles describe the question, not the metric name.
- Legends retain useful bounded dimensions only.
