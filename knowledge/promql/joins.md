# PromQL joins and vector matching

## Start with identity

Before writing a join, state the unique identity of each side.

Examples:

- `(namespace,pod,container)`
- `(cluster,namespace,pod)`
- `(namespace,replicaset)`

Do not add `group_left` or `group_right` until uniqueness is verified.

Vector-to-vector arithmetic/comparison keeps only label sets that match under
the chosen matching rules. An unmatched series does not automatically become
zero; read `missing-series.md` when absence matters.

## One-to-one

Use `on(...)` or `ignoring(...)` to define matching explicitly when default full-label matching is not correct.

`on(a,b)` means only those labels define the match. `ignoring(x,y)` means all
other labels still participate. Choose the form that matches the verified
identity; do not use a shorter matcher merely to make the query execute.

Example shape:

```promql
errors
/
on (namespace, pod)
requests
```

Both sides must be unique for `(namespace,pod)` after their own aggregation.

## Many-to-one / one-to-many

`group_left` and `group_right` are declarations about cardinality, not generic fixes for many-to-many errors.

Verify the "one" side is actually unique for the selected match labels. A group
modifier permits the intended many-to-one/one-to-many relation; it does not make
a many-to-many relation valid.

Use the optional label list on `group_left(...)`/`group_right(...)` only for
labels that must be copied from the one-side into the result. Do not carry
unbounded metadata into the result without a planned need.

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

Normalize before matching only when the transformation is deterministic and
validated. Repeated regex rewriting over high-cardinality vectors is also a
query-cost concern; read `performance.md`.

## Cardinality

Estimate both input series and output series. A semantically correct join can still be unsuitable for an interactive dashboard if it multiplies high-cardinality dimensions.
