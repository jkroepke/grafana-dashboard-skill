# Grafana Dashboard Schema V2 and Grafonnet layout

## Schema

Default new dashboards to Dashboard Schema V2. Preserve classic schema for existing classic dashboards unless migration is requested.

Use the pinned generated `grafana/grafonnet` API. Inspect unfamiliar local generated methods instead of guessing signatures or patch shapes.

A generic schema field may require a schema-checked Jsonnet object when no typed builder exists. Do not wrap classic panels in invented V2 envelopes.

## V2 structure

Current Dashboard Schema V2 separates dashboard elements from layout. Panels live in the dashboard `elements` map and layout items reference those element names.

Validate every layout reference after rendering. Do not assume classic `gridPos` placement applies to V2.

V2 supports four layout kinds:

| Kind | Use |
| --- | --- |
| `AutoGridLayout` | similarly sized panels where automatic placement is sufficient |
| `GridLayout` | deliberate width, height, or position differences |
| `RowsLayout` | row-based grouping/collapse when sections need it |
| `TabsLayout` | tabbed sections when each tab contains enough useful content |

Rows and tabs contain nested layouts. Keep nesting shallow.

Tabs can have section-local behavior in the schema, but keep the required `datasource`, `namespace`, and `pod` variables dashboard-global. Do not shadow them inside tabs/rows.

## Layout rules

- prefer `AutoGridLayout` for regular panel sets
- use `GridLayout` only when panel size/position differences carry meaning
- use `RowsLayout` or `TabsLayout` only when grouping improves navigation
- omit empty sections
- do not force tabs onto a small dashboard
- do not duplicate the same panel element into multiple places unless the pinned schema explicitly supports the intended behavior

The coordinator owns final layout integration. The panel expert only recommends placement and sizing.

## Source

- preserve dashboard identity and unrelated panels on focused updates
- preserve dependency pins
- create `.libsonnet` helpers only when they materially reduce duplication
- keep code-managed dashboards non-editable unless repository policy says otherwise

## Validation

Render with repository commands and check:

- schema version
- `elements` keys and layout references
- selected layout kinds
- variable types and order
- datasource references
- unique panel IDs where applicable
- query modes
- units
- annotations

`jq empty` proves JSON syntax only.
