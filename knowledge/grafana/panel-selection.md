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

## Dashboard V2 visualization identity

Do not confuse a panel's descriptive identity with its visualization plugin identity.

In Dashboard Schema V2:

- `spec.elements` is a map keyed by dashboard-local element names
- those element keys may be descriptive strings such as `overview-mean-pages`
- a normal panel element uses `kind: Panel`
- the visualization is configured separately; its panel plugin ID is normally stored in `spec.vizConfig.group`

Grafana itself uses a real plugin ID such as `timeseries` for a Time series visualization. Do not construct `vizConfig.group` from an element key, panel title, placement, metric name, or question.

A valid-looking string is not evidence that a panel plugin exists. The Dashboard V2 schema can represent plugin identity without proving that the target Grafana has that plugin available.

Resolve every visualization plugin ID from local/target evidence:

1. use the pinned Grafonnet constructor when it provides the visualization
2. otherwise inspect the target Grafana plugin inventory, for example `GET /api/plugins`, and require an installed panel plugin
3. otherwise inspect the pinned/local Grafana panel plugin schema or source

If the plugin ID cannot be verified, do not generate that panel. Prefer another verified built-in visualization that answers the same operational question.

Do not maintain a guessed static list of plugin IDs when the target Grafana or pinned dependency can provide the answer.

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
- Never use a dashboard element name as `vizConfig.group` unless target evidence independently proves a panel plugin with exactly that ID exists.
