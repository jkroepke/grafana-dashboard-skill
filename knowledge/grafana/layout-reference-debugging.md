# Dashboard V2 element references

Read this file when creating/reviewing V2 layouts or when Grafana reports that a panel referenced by a layout cannot be found.

## Reference semantics

Dashboard Schema V2 stores panel elements in `spec.elements`, a map keyed by dashboard-local element names.

A layout item references an element with:

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

Inspect the exact rendered dashboard sent to Grafana and the exact resource returned by Grafana after publication.

For the stored resource, compare element keys with all layout element references:

```bash
jq -r '.spec.elements | keys[]' stored-dashboard.json | sort -u

jq -r '.spec.layout | .. | objects | select(.kind? == "ElementReference") | .name' stored-dashboard.json | sort -u
```

To print references that have no matching element key:

```bash
comm -23 \
  <(jq -r '.spec.layout | .. | objects | select(.kind? == "ElementReference") | .name' stored-dashboard.json | sort -u) \
  <(jq -r '.spec.elements | keys[]' stored-dashboard.json | sort -u)
```

Any output is a broken layout reference.

For every `ElementReference.name = X`, require an exact `spec.elements[X]` key in the same stored dashboard spec. Matching is exact and case-sensitive.

If the rendered source has the key but the stored resource does not, investigate the publication request/envelope or schema/API version. Do not change the reference model to UID-based lookup.

If the stored resource has a different element key, fix either the element key or the layout reference so they are identical. Prefer keeping stable descriptive element keys when updating an existing dashboard.
