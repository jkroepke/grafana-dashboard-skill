# Dashboard V2 validation error diagnosis

Read this file whenever a target-Grafana Dashboard V2 dry-run fails.

The purpose is to diagnose the exact failing schema branch without inventing explanations from error wording.

## Hard rules

- MUST preserve the complete dry-run response body before reasoning about the failure.
- MUST identify the exact request body that produced the error.
- MUST use the pinned/local `dashboard.grafana.app/v2` contract; do not fetch target OpenAPI/Swagger.
- MUST distinguish CUE disjunction branch errors from the actual selected-branch error.
- MUST NOT infer that Grafana saw multiple layouts merely because an error lists several layout kinds.
- MUST NOT infer that a layout kind is unsupported merely because the other disjunction branches report `conflicting values`.
- MUST NOT call a failure a Grafana bug, version quirk, schema quirk, unsupported feature, or discriminator ambiguity until a minimal target-side probe demonstrates that conclusion.
- MUST NOT change the layout discriminator, add generated union-wrapper field names, or bypass strict validation merely to make the error disappear.
- MUST fix Jsonnet/Grafonnet source. A temporary diagnostic request/file may simplify the candidate, but patching rendered JSON is not the final fix.

When the root cause is not yet proven, say it is unresolved and continue isolation. Do not fill the gap with a theory.

## First classify the failure

Classify the complete response before changing source:

1. HTTP/routing/authentication failure
2. strict decoder failure: unknown or duplicate fields
3. CUE/schema validation failure: empty disjunction, conflicting values, missing fields, invalid bounds, or type mismatch
4. Dashboard conversion/admission/deserialization failure
5. Dashboard semantic failure after decoding, for example an unresolved element reference

Do not mix explanations from different layers.

## CUE disjunctions: read all branch errors correctly

Grafana Dashboard V2 defines layout as a CUE disjunction conceptually equivalent to:

```cue
layout: GridLayoutKind | RowsLayoutKind | AutoGridLayoutKind | TabsLayoutKind
```

A CUE disjunction succeeds when one branch satisfies all constraints. When no branch succeeds, CUE reports failures from the alternatives. Therefore a request with:

```json
{
  "kind": "AutoGridLayout",
  "spec": { ... }
}
```

can legitimately produce errors such as:

```text
conflicting values "GridLayout" and "AutoGridLayout"
conflicting values "RowsLayout" and "AutoGridLayout"
conflicting values "TabsLayout" and "AutoGridLayout"
```

Those three messages are expected failures of the non-selected branches. They do **not** mean:

- four layouts were present in the JSON
- Grafana could not read the discriminator
- `AutoGridLayout` is unsupported
- the server selected all layout kinds
- the payload needs `GridLayoutKind`, `RowsLayoutKind`, `TabsLayoutKind`, or `AutoGridLayoutKind` wrapper properties

If `spec.layout.kind == "AutoGridLayout"`, the diagnostic target is the **AutoGridLayout branch**. Find the other error that explains why that branch failed.

The same rule applies recursively to other CUE unions in Dashboard V2.

## Mandatory disjunction procedure

When the error contains `empty disjunction` or several `conflicting values` messages:

1. Read the exact discriminator from the submitted request.
2. Identify the schema branch whose discriminator matches it.
3. Mark discriminator conflicts from all other branches as expected branch noise.
4. Search the complete error details for a non-discriminator error in the matching branch: missing field, invalid field, invalid value, type mismatch, nested union failure, or another constraint.
5. Fix only the evidenced matching-branch problem in Grafonnet source.
6. Render again and repeat the same target dry-run.

For a layout candidate, inspect:

```bash
jq '.spec.layout' rendered-dashboard.json
jq -r '.spec.layout.kind' rendered-dashboard.json
jq '.spec.layout.spec' rendered-dashboard.json
```

Never stop analysis after reading only the first `conflicting values` line.

## Capture the full Grafana failure

Do not discard the response body on HTTP 4xx/5xx. Use the configured authenticated wrapper and equivalent curl options to persist both headers and body, for example:

```bash
<grafana-curl> -sS --fail-with-body \
  -D /tmp/grafana-dry-run.headers \
  -o /tmp/grafana-dry-run.response.json \
  -X POST \
  '<target-dashboard-resource-url>?dryRun=All&fieldValidation=Strict' \
  -H 'Content-Type: application/json' \
  --data-binary @rendered-dashboard.json
```

Then inspect the complete body:

```bash
jq . /tmp/grafana-dry-run.response.json
```

If the response is not JSON, inspect it as text. Do not paste credentials or authorization headers into findings.

## Layout wire format: do not copy the generated union wrapper

Dashboard V2's generated Go/OpenAPI model represents the layout union internally with named arms similar to:

```text
GridLayoutKind
RowsLayoutKind
AutoGridLayoutKind
TabsLayoutKind
```

That internal representation is **not the Dashboard JSON wire shape**.

Grafana's generated union type uses custom JSON marshal/unmarshal logic. On the wire an AutoGrid layout is flattened to:

```json
{
  "kind": "AutoGridLayout",
  "spec": {
    "items": []
  }
}
```

The server selects the internal union arm from the top-level `kind` value.

Do NOT change the wire payload to:

```json
{
  "AutoGridLayoutKind": {
    "kind": "AutoGridLayout",
    "spec": {
      "items": []
    }
  }
}
```

merely because a generated OpenAPI component or language binding exposes `AutoGridLayoutKind` as a property. That is an internal generated representation, not the JSON shape consumed by the Dashboard V2 API.

The same caution applies when reading generated language bindings for other flattened CUE unions: verify custom marshal/unmarshal behavior or an actual target-produced resource before copying union-arm property names into JSON.

## Grafonnet v13 layout union trap

Grafonnet v13 exposes both the union namespace and nested layout-kind builders. For Dashboard V2 wire JSON, use the canonical direct path mixins:

```jsonnet
local d = g.apps.dashboard.v2;
local auto = d.spec.layout.AutoGridLayoutKind;

local dashboard =
  d.new('my-dashboard', 'My Dashboard')
  + auto.withKind()
  + auto.spec.withItems(items);
```

These render the required flattened wire shape:

```json
"layout": {
  "kind": "AutoGridLayout",
  "spec": {
    "items": []
  }
}
```

Do not switch to a wrapper-producing composition such as:

```jsonnet
d.spec.layout.withAutoGridLayoutKind({
  kind: 'AutoGridLayout',
  spec: { items: [] },
})
```

if it renders an `AutoGridLayoutKind` property in the JSON. The generic rule "use generated builders" does not mean "use every generated setter". Use the generated builder composition that produces the target Dashboard wire contract.

When uncertain, render a minimal builder expression and inspect the JSON before integrating it.

## Minimal target-side probe

If the matching-branch error is still unclear, reduce the failing structure before inventing a theory.

A diagnostic probe is temporary and must use:

- the same target Grafana
- the same Dashboard API version
- namespace `default`
- the same dry-run mechanism
- strict field validation when advertised
- the same canonical wire representation

For AutoGrid, start with the smallest candidate the pinned builder/schema permits. Conceptually:

```jsonnet
local d = g.apps.dashboard.v2;
local auto = d.spec.layout.AutoGridLayoutKind;

d.new('dry-run-probe', 'Dry-run probe')
+ auto.withKind()
+ auto.spec.withItems([])
```

Use the pinned local builders and add any fields the target schema genuinely requires. Do not guess them from model memory.

Interpret the result:

- Minimal AutoGrid passes: the discriminator and AutoGrid support are proven. Reintroduce candidate fields/items incrementally until the failing field is isolated.
- Minimal AutoGrid fails with a concrete matching-branch constraint: fix that constraint and retry.
- Minimal AutoGrid still fails but only disjunction branch noise is visible: capture the complete server details and compare with a target-produced V2 resource/schema before changing representation.
- A target-produced AutoGrid resource fails unchanged on its own advertised dry-run route: only then investigate a target/server bug or version-specific defect.

Prefer binary isolation for a large `spec`: remove half of optional properties or item groups in a diagnostic copy, dry-run, and continue with the failing half. Do not randomly change unrelated fields.

## Compare with target-produced evidence

When local knowledge and target behavior disagree, use evidence in this order:

1. a Dashboard V2 resource returned by that target Grafana
2. locally pinned Grafana/Grafonnet generated schema/code for the target version
3. repository knowledge

Do not fetch target OpenAPI/Swagger; the only target-version request is the
coordinator's one opaque `/version` command.

Do not use a newer public schema to override a pinned target.

If an existing working Dashboard uses the same layout kind, compare only the relevant structure:

```bash
jq '.spec.layout' working-dashboard.json
jq '.spec.layout' rendered-dashboard.json
```

Compare field names, types, required nested objects, and item structure. Do not copy unrelated dashboard content.

## Strict versus non-strict requests

`fieldValidation=Strict` is intentionally part of validation.

If strict dry-run fails but a non-strict request succeeds:

- do not accept the non-strict result as a pass
- do not remove `fieldValidation=Strict` as a workaround
- find the exact field that strict decoding rejects
- fix the source or prove a target API/schema defect with a minimal reproducer

Unknown fields being silently dropped are a correctness failure for a code-managed dashboard.

## Reviewer finding quality

A finding must separate evidence from interpretation.

Good:

```text
FAIL

1. AutoGrid dry-run fails in the selected AutoGrid branch.
   Evidence: request spec.layout.kind=AutoGridLayout; Grid/Rows/Tabs kind conflicts are nonmatching CUE branches; target additionally rejects spec.layout.spec.<field> with <exact error>.
   Required correction: fix <field> in Grafonnet source and repeat strict dry-run.
```

If isolation has not found the matching-branch error yet:

```text
FAIL

1. Target Dashboard V2 dry-run still fails; root cause unresolved.
   Evidence: request contains only kind=AutoGridLayout. Reported Grid/Rows/Tabs conflicts are CUE alternative-branch failures and do not prove multiple layouts.
   Required correction: preserve the current discriminator and run the minimal AutoGrid probe / inspect complete target error details. Do not apply a speculative layout or wrapper change.
```

Do not report a guessed root cause as evidence.
