# PromQL joins and vector matching

## Start with identity

Before writing a join, state the unique identity of each side.

Examples:

- `(namespace,pod,container)`
- `(cluster,namespace,pod)`
- `(namespace,replicaset)`

Do not add `group_left` or `group_right` until uniqueness is verified.

## One-to-one

Use `on(...)` or `ignoring(...)` to define matching explicitly when default full-label matching is not correct.

## Many-to-one / one-to-many

`group_left` and `group_right` are declarations about cardinality, not generic fixes for many-to-many errors.

Verify the "one" side is actually unique for the selected match labels.

## Duplicate observations

Exporter replicas, duplicate scrape paths, or recording rules can produce multiple observations with the same logical identity.

Do not apply generic `max`, `min`, or `sum` deduplication without identifying why duplicates exist and which semantics are correct.

## Label preservation

Keep only labels needed for:

- unique matching
- final grouping
- useful legend/panel dimensions

Dropping identity too early can create accidental many-to-many joins.

## `label_replace` / `label_join`

Use label rewriting only when the source contract genuinely requires normalization. Do not use regex label rewriting to guess workload ownership when direct owner metrics exist.

## Cardinality

Estimate both input series and output series. A semantically correct join can still be unsuitable for an interactive dashboard if it multiplies high-cardinality dimensions.
