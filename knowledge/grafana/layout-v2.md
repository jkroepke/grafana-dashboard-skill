# Grafana Dashboard Schema V2 and Grafonnet layout

## Schema

Default new dashboards to Dashboard Schema V2. Preserve classic schema for existing classic dashboards unless migration is requested.

Use the pinned generated `grafana/grafonnet` API. Inspect unfamiliar local generated methods instead of guessing signatures or patch shapes.

For Dashboard Schema V2, read `knowledge/grafana/grafonnet-v2.md` before writing or reviewing the Grafonnet source. The model's built-in knowledge of Grafonnet may be stale; the local vendored generated API is authoritative.

Do not reject the `grafonnet-latest` import path by name alone. Resolve what the vendored alias and jsonnet-bundler lock actually point to. Preserve the repository import convention and dependency pin.

Distinguish the classic `grafonnet.dashboard` / `grafonnet.panel` APIs from the Dashboard V2 resource API under `grafonnet.apps.dashboard.v2`. A classic panel object must not be inserted directly into V2 `spec.elements`; V2 elements require the `PanelKind` structure expected by the pinned Dashboard V2 schema.

Use generated V2 builders where the pinned library provides them. A generic schema field may require a schema-checked Jsonnet object when no typed builder exists; Grafonnet v13 notably exposes `spec.withElements(object)` without a typed `PanelKind` builder. Do not invent a builder that is absent, and do not wrap classic panels in invented V2 envelopes.

## V2 structure

Current Dashboard Schema V2 separates dashboard elements from layout. Panels live in the dashboard `elements` map and layout items reference those element names.

For a layout reference:

```json
{
  "kind": "ElementReference",
  "name": "overview-mean-pages"
}
```

Grafana resolves the panel as:

```text
spec.elements["overview-mean-pages"]
```

The `name` must exactly match a key in `spec.elements`. Do not convert this into UID-based lookup and do not add a guessed panel `uid` field. Normal V2 `PanelKind` uses `kind: "Panel"`; `PanelSpec` has a numeric `id`.

Grafana may misleadingly report `Panel with uid <name> not found in the dashboard elements`. The implementation still looks up `elements[item.spec.element.name]`. Treat that error as a missing/mismatched `spec.elements` key or as an invalid element that failed to become a usable V2 panel.

When that error occurs, read `knowledge/grafana/layout-reference-debugging.md` and inspect the Grafonnet source, exact rendered dashboard, and exact stored dashboard resource before changing the model.

Validate every layout reference after rendering and again on the resource returned by Grafana after publication. Do not assume classic `gridPos` placement applies to V2.

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
- require every `ElementReference.name = X` to have an exact `spec.elements[X]` key
- never infer element-reference semantics from the word `uid` in Grafana error text
- use the pinned generated layout-item/element-reference builders instead of hand-writing their JSON when those builders exist

The coordinator owns final layout integration. The panel expert only recommends placement and sizing.

## Source

- preserve dashboard identity and unrelated panels on focused updates
- preserve dependency pins and import conventions
- resolve `grafonnet-latest` through the vendored alias/lock instead of assuming it is unpinned
- use `grafonnet.apps.dashboard.v2` for a Dashboard Schema V2 resource; `grafonnet.dashboard.new(...)` is the classic dashboard surface
- do not put direct `grafonnet.panel.*.new(...)` results into V2 `spec.elements`
- use generated V2 builders where available; use schema-shaped raw objects only where the pinned library has no suitable builder
- create `.libsonnet` helpers only when they materially reduce duplication or safely encapsulate a verified V2 structure
- keep code-managed dashboards non-editable unless repository policy says otherwise

## Validation

Render with repository commands and check:

- schema version
- V2 root resource was built from the intended Grafonnet API
- every element intended as a panel renders with `kind: "Panel"`
- panel `spec` contains the V2 `data` / `vizConfig` structure required by the pinned schema
- V2 DataQuery wrappers and datasource references use the pinned V2 shape rather than classic query DTO assumptions
- `elements` keys and layout references
- selected layout kinds
- variable types and order
- datasource references
- unique panel IDs where applicable
- query modes
- units
- annotations

For V2, compare all layout element-reference names with the keys of `spec.elements`. Static schema validity alone is not enough; a schema-valid reference can still name a nonexistent or unusable element.

`jq empty` proves JSON syntax only.
