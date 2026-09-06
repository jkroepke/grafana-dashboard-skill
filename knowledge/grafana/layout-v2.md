# Grafana Dashboard Schema V2 and Grafonnet layout

## Schema

Default new dashboards to Dashboard Schema V2. Preserve classic schema for existing classic dashboards unless migration is requested.

Use the pinned generated `grafana/grafonnet` API. Inspect unfamiliar local generated methods instead of guessing signatures or patch shapes.

A generic schema field may require a schema-checked Jsonnet object when no typed builder exists. Do not wrap classic panels in invented V2 envelopes.

## Grafonnet construction

Author Dashboard V2 through the pinned Grafonnet builders. Treat rendered JSON as the result to validate, not as the primary authoring format.

Inspect the locally pinned Grafonnet revision first. Generated method names can change between revisions; local generated code/docs are authoritative over upstream examples.

The current generated Grafonnet V2 API exposes the relevant concepts as:

- dashboard `spec.withElements(value)` / `spec.withElementsMixin(value)`
- dashboard `spec.withLayout(value)` / layout-kind builders
- `AutoGridLayoutKind.spec.withItems(value)` / `withItemsMixin(value)`
- AutoGrid item `spec.element.withKind()`
- AutoGrid item `spec.element.withName(value)`

Use the equivalent methods from the pinned local revision.

For each panel, define the dashboard-local element name once and reuse that same value for both sides of the relationship:

```jsonnet
local elementName = 'overview-mean-pages';

// Conceptual shape only; use the actual pinned Grafonnet object paths.
local elements = { [elementName]: panel };
local elementRef =
  <autoGridItem>.spec.element.withKind()
  + <autoGridItem>.spec.element.withName(elementName);
```

Pass `elements` through the pinned dashboard `spec.withElements{,Mixin}` builder and `elementRef` through the pinned AutoGrid item builder. Do not duplicate the name as unrelated string literals when one local value can be reused.

Prefer typed Grafonnet builders over raw `{ kind: ..., name: ... }` schema objects. Use a raw schema-checked Jsonnet object only when the pinned Grafonnet revision has no builder for that field.

Never add a guessed panel UID to repair a layout reference. Fix the Grafonnet source that constructs the element map or reference, then render again.

## V2 structure

Dashboard Schema V2 separates dashboard elements from layout. Panels live in the dashboard `elements` map and layout items reference those element names.

The rendered reference has the shape:

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

Grafana may misleadingly report `Panel with uid <name> not found in the dashboard elements`. The implementation still looks up `elements[item.spec.element.name]`. Treat that error as a missing/mismatched `spec.elements` key.

When that error occurs, read `knowledge/grafana/layout-reference-debugging.md` and trace the pinned Grafonnet source before changing the model.

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
- construct both sides from the same Grafonnet element-name value where practical
- never infer element-reference semantics from the word `uid` in Grafana error text

The coordinator owns final layout integration. The panel expert only recommends placement and sizing.

## Source

- preserve dashboard identity and unrelated panels on focused updates
- preserve dependency pins
- inspect pinned Grafonnet generated APIs before writing V2 builder code
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

For V2, compare all rendered layout element-reference names with the keys of rendered `spec.elements`. Static schema validity alone is not enough; a schema-valid reference can still name a nonexistent element.

When a reference fails, fix the Grafonnet source and render again. Do not patch the rendered JSON as the solution.

`jq empty` proves JSON syntax only.
