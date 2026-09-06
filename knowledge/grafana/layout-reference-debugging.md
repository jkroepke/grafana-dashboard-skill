# Dashboard V2 element references

Read this file when creating/reviewing V2 layouts or when Grafana reports that a panel referenced by a layout cannot be found.

## Grafonnet first

The dashboard source is Grafonnet/Jsonnet. Diagnose and fix the source first; rendered JSON and the Grafana resource are validation artifacts.

Inspect the pinned local Grafonnet revision rather than guessing builder APIs. For current generated Grafonnet V2, the relevant API concepts include:

- dashboard `spec.withElements(value)` / `spec.withElementsMixin(value)`
- `AutoGridLayoutKind.spec.withItems(value)` / `withItemsMixin(value)`
- AutoGrid item `spec.element.withKind()`
- AutoGrid item `spec.element.withName(value)`

Use the equivalent methods exposed by the pinned local revision.

For each layout item, trace the source value passed to `spec.element.withName(...)` back to the key used in the object passed to `spec.withElements{,Mixin}`.

Prefer one Jsonnet local for both:

```jsonnet
local elementName = 'overview-mean-pages';

// Conceptual shape; use the actual pinned Grafonnet object paths.
local elements = { [elementName]: panel };
local elementRef =
  <autoGridItem>.spec.element.withKind()
  + <autoGridItem>.spec.element.withName(elementName);
```

If the two sides use separate literals or generated names, verify that they evaluate to the exact same string. Fix mismatches in Grafonnet source and render again.

Do not patch the rendered JSON as the fix. Do not replace a Grafonnet element reference with a guessed UID model.

## Reference semantics

Dashboard Schema V2 stores panel elements in `spec.elements`, a map keyed by dashboard-local element names.

A rendered layout item references an element with:

```json
{
  "kind": "ElementReference",
  "name": "overview-mean-pages"
}
```

The `name` is looked up directly as a key in `spec.elements`:

```text
spec.elements[layoutItem.spec.element.name]
```

Therefore this is valid when the map contains the same key:

```json
{
  "spec": {
    "elements": {
      "overview-mean-pages": {
        "kind": "Panel",
        "spec": {
          "id": 1,
          "title": "Mean pages"
        }
      }
    }
  }
}
```

Do not replace `ElementReference.name` with a guessed UID field.

## Misleading Grafana error

Grafana can emit an error like:

```text
Panel with uid overview-mean-pages not found in the dashboard elements
```

Do not infer UID semantics from the wording of that error.

The Grafana AutoGrid deserializer performs the lookup by `element.name` against the `elements` map. The word `uid` in the error message does not mean that a normal V2 `Panel` element requires a UID field.

A normal V2 `PanelKind` contains `kind: "Panel"` and `spec`. `PanelSpec` has a numeric `id`; do not invent a panel `uid` field.

## Diagnose a missing element

Use this order:

1. Inspect the Jsonnet/Grafonnet source that constructs the panel element map and layout item.
2. Inspect the pinned generated Grafonnet methods used by that source.
3. Render the dashboard from source.
4. Compare rendered `spec.elements` keys with rendered layout references.
5. If publication occurred, GET the stored dashboard resource and perform the same comparison there.

For a rendered or stored resource, compare element keys with all layout element references:

```bash
jq -r '.spec.elements | keys[]' dashboard.json | sort -u

jq -r '.spec.layout | .. | objects | select(.kind? == "ElementReference") | .name' dashboard.json | sort -u
```

To print references that have no matching element key:

```bash
comm -23 \
  <(jq -r '.spec.layout | .. | objects | select(.kind? == "ElementReference") | .name' dashboard.json | sort -u) \
  <(jq -r '.spec.elements | keys[]' dashboard.json | sort -u)
```

Any output is a broken layout reference.

For every `ElementReference.name = X`, require an exact `spec.elements[X]` key in the same dashboard spec. Matching is exact and case-sensitive.

Interpret the result by stage:

- Grafonnet source already uses different names: fix the source.
- Source appears consistent but rendered JSON differs: inspect the pinned Grafonnet builder composition and mixin usage.
- Rendered JSON is correct but stored resource differs: investigate the publication request envelope, API version, or server transformation.
- Stored resource contains both the exact element key and reference but Grafana still reports the error: capture the exact returned resource and Grafana version; do not invent a UID field.

Prefer keeping stable descriptive element keys when updating an existing dashboard.
