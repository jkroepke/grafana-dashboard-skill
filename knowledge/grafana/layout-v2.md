# Grafana Dashboard Schema V2 and Grafonnet layout

## Schema

This workflow handles only Dashboard Schema V2 resources on Grafana v13+. Every new candidate and any existing baseline must be V2; reject classic dashboard JSON instead of preserving or migrating it.

Use the pinned generated `grafana/grafonnet` API. Inspect unfamiliar local generated methods instead of guessing signatures or patch shapes.

**MUST read both `knowledge/grafana/grafonnet-v2.md` and `knowledge/grafana/grafonnet-builder-composition.md` before writing or reviewing the Grafonnet source.** The model's built-in knowledge of Grafonnet may be stale; the local vendored generated API is authoritative.

Do not reject the `grafonnet-latest` import path by name alone. Resolve what the vendored alias and jsonnet-bundler lock actually point to. Preserve the repository import convention and dependency pin.

Distinguish the classic `grafonnet.dashboard` / `grafonnet.panel` APIs from the Dashboard V2 resource API under `grafonnet.apps.dashboard.v2`. A classic panel object must not be inserted directly into V2 `spec.elements`; V2 elements require the `PanelKind` structure expected by the pinned Dashboard V2 schema.

## Non-negotiable Grafonnet builder rule

For Dashboard Schema V2:

- **MUST use the pinned generated Grafonnet builder whenever that builder exists.**
- **MUST NOT hand-author an equivalent raw Jsonnet/JSON object merely because its schema shape is known.**
- **MUST inspect the local vendored generated API before deciding that no builder exists.**
- **MUST classify the generated builder as a path mixin or standalone value before composing it.**
- **MUST NOT feed a path-mixin result back into a parent `withX(...)` setter when the generated result already contains that parent path.**
- Raw schema-shaped Jsonnet is allowed only when the pinned Grafonnet API genuinely has no suitable builder, or when the repository contains a documented compatibility workaround for the exact pinned version.
- A manual equivalent of an available builder is a correctness failure, not a style preference.
- A double-wrapped builder result is also a correctness failure, even when Jsonnet renders successfully.
- Do not patch rendered JSON to compensate for incorrect source construction.

This requirement applies to the V2 resource envelope, metadata, layouts, layout items, element references, variables, annotations, time settings, and every other V2 structure for which the pinned library provides a builder.

Grafonnet v13 notably exposes `spec.withElements(object)` without a typed `PanelKind`/`QueryGroup` constructor. Schema-shaped raw Jsonnet is therefore acceptable for those unmodeled V2 panel internals, but the surrounding dashboard/layout/variable/annotation structures must still use available generated builders.

### Builder composition model

Generated Grafonnet namespaces are not uniformly standalone constructors.

For v13, `d.spec.layout.AutoGridLayoutKind.withKind()` and `d.spec.layout.AutoGridLayoutKind.spec.withItems(...)` are **dashboard path mixins**: their generated bodies already write to `spec.layout`. Compose them directly onto `d.new(...)`. Do not put their result into `d.spec.withLayout(...)`.

By contrast, `d.spec.layout.AutoGridLayoutKind.spec.items.withKind()` builds a standalone `AutoGridLayoutItem`, and `d.spec.variables.QueryVariableKind.withKind()` builds a standalone variable. Compose their nested mixins into those standalone items, then pass the completed items to `withItems(...)` or `withVariables(...)`.

Nested query builders such as `QueryVariableKind.spec.query.withKind()` are path mixins relative to the variable object. Compose them directly into the variable. Do not build that wrapped fragment separately and then pass it to `QueryVariableKind.spec.withQuery(...)`.

Use exactly one composition route for a field:

1. generated path mixins composed directly into the owning object, or
2. a true standalone inner value passed to a parent `withX(value)` setter.

Never use both routes for the same field. See `knowledge/grafana/grafonnet-builder-composition.md` for canonical AutoGrid, variable, query, annotation, and validation examples.

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
- **MUST use the pinned generated layout-item and element-reference builders when they exist; hand-written `{kind: ...}` equivalents are forbidden unless a documented compatibility exception exists**
- **MUST compose AutoGrid path mixins directly onto the dashboard; do not wrap them again with `spec.withLayout(...)`**

`dashboard-architect` owns conceptual placement and sizing. `dashboard-builder` owns staged layout integration, and `dashboard-reviewer` independently verifies the rendered layout before the coordinator mechanically promotes the approved candidate.

## Source

- preserve dashboard identity and unrelated panels on focused updates
- preserve dependency pins and import conventions
- resolve `grafonnet-latest` through the vendored alias/lock instead of assuming it is unpinned
- use `grafonnet.apps.dashboard.v2` for a Dashboard Schema V2 resource; `grafonnet.dashboard.new(...)` is the classic dashboard surface
- do not put direct `grafonnet.panel.*.new(...)` results into V2 `spec.elements`
- **MUST use generated V2 builders where available**
- classify each unfamiliar builder by its generated return fragment before composing it
- use schema-shaped raw objects only where the pinned library has no suitable builder, and verify that absence from the local generated API before proceeding
- create `.libsonnet` helpers only when they materially reduce duplication or safely encapsulate a verified V2 structure
- keep code-managed dashboards non-editable unless repository policy says otherwise

## Validation

For a candidate dashboard, `dashboard-builder` runs `jsonnetfmt -i`, renders
with `jsonnet -J vendor`, and parses the result with `jq empty`;
`scripts/dashboard_integrity.py` performs the fixed integrity gate.
Then check:

- schema version
- V2 root resource was built from the intended Grafonnet API
- available generated V2 builders were used instead of manual equivalents
- no generated path mixin was double-wrapped through a parent setter
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
