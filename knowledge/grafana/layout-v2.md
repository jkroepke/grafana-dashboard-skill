# Grafana Schema V2 and Grafonnet layout

## Schema

Default new dashboards to Schema V2. Preserve classic schema for existing classic dashboards unless migration is requested.

Use the pinned generated `grafana/grafonnet` API. Inspect unfamiliar local generated methods instead of guessing signatures or patch shapes.

A generic schema field may require a schema-checked Jsonnet object when no typed builder exists. Do not wrap classic panels in invented V2 envelopes.

## Layout

For V2:

- prefer AutoGrid for panels with similar sizes
- use custom grid for deliberate width/height differences
- use tabs such as Application, Kubernetes, Runtime only when each contains enough useful content
- omit empty sections
- keep nesting shallow
- do not force tabs onto a small dashboard

The coordinator owns final layout integration. The panel expert only recommends placement and sizing.

## Source

- preserve dashboard identity and unrelated panels on focused updates
- preserve dependency pins
- create `.libsonnet` helpers only when they materially reduce duplication
- keep code-managed dashboards non-editable unless repository policy says otherwise

## Validation

Render with repository commands and check:

- schema version
- V2 element/layout references
- variable types and order
- datasource references
- unique panel IDs where applicable
- query modes
- units
- annotations

`jq empty` proves JSON syntax only.
