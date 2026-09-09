# Grafana Dashboard V2 server-side dry-run validation

Read this file when reviewing a rendered Dashboard Schema V2 resource against a real Grafana instance.

## Purpose

Use Grafana's own Dashboard resource API as a final schema/admission check before the reviewer can return `PASS`.

This is validation only. A dry-run request MUST NOT be treated as publication.

## Hard rule

When target Grafana dashboard API access is configured:

- the reviewer MUST submit the rendered Dashboard resource using the pinned/local stable V2 dry-run mechanism
- the reviewer MUST use the Dashboard resource namespace `default`
- the reviewer MUST use `dashboard.grafana.app/v2`
- the reviewer MUST enable strict field validation
- the reviewer MUST NOT return `PASS` if the dry-run request fails
- the reviewer MUST inspect the dry-run response body, not only the HTTP status
- on any dry-run failure, the reviewer MUST read `knowledge/grafana/v2-validation-errors.md` before changing or recommending a source change
- credentials and authorization headers MUST NOT be printed in review output

If the configured API wrapper cannot perform the stable V2 dry-run for the
exact create or update operation, record Dashboard API validation as absent in
the run contract. Do not use a create dry-run as a substitute for an update
dry-run, and do not bypass the opaque wrapper. If the task requires server-side
validation, stop with a bounded validation-gap failure.

## Source of truth

The coordinator establishes Grafana compatibility before dispatch. Reviewers
do not repeat or inspect that gate.

Use the repository's pinned/local stable V2 request shapes. Do not fetch,
inspect, or cache target OpenAPI/Swagger in this stage or any other workflow
stage. Do not bypass the configured API wrapper with direct network access.

This workflow requires stable `dashboard.grafana.app/v2` on Grafana v13+. If the target exposes only another structured version such as `v2beta1`, stop rather than substituting it.

Do not assume the latest public Grafana behavior for an air-gapped/pinned target.

## Stable V2 request form

For current stable Dashboard V2, `dryRun` follows Kubernetes API semantics. The accepted value is `All`.

Use:

```text
dryRun=All
```

Do NOT use:

```text
dryRun=true
```

`dryRun=true` is not valid for this workflow.

Always use strict field validation:

```text
fieldValidation=Strict
```

This makes unknown/duplicate fields fail instead of being silently ignored.

## New dashboard

For a dashboard that does not already exist, stable V2 validation is normally:

```text
POST /apis/dashboard.grafana.app/v2/namespaces/default/dashboards?dryRun=All&fieldValidation=Strict
```

Request body: the rendered Dashboard resource.

Example shape:

```bash
curl -fsS \
  -X POST \
  "$GRAFANA_URL/apis/dashboard.grafana.app/v2/namespaces/default/dashboards?dryRun=All&fieldValidation=Strict" \
  -H 'Content-Type: application/json' \
  --data-binary @rendered-dashboard.json
```

Use the repository's configured authenticated wrapper/mechanism instead of inventing authentication.

When diagnosing a failure, use an opaque wrapper that preserves the complete
response body and headers even on an HTTP error. See
`knowledge/grafana/v2-validation-errors.md`. If the configured wrapper does
not offer that capability, retain its failure locally and stop rather
than constructing a direct request.

## Existing dashboard

For an existing dashboard, validate the same operation the publisher would perform.

1. GET the live resource first.
2. Preserve server-managed metadata required for replacement, especially the live resource identity/resource version when required by the target API.
3. Preserve folder placement unless the source intentionally changes it.
4. Replace the dashboard `spec` with the rendered candidate `spec`.
5. Submit the candidate using the target's replace/update endpoint with dry-run enabled.

For current stable V2 this is normally:

```text
PUT /apis/dashboard.grafana.app/v2/namespaces/default/dashboards/<metadata.name>?dryRun=All&fieldValidation=Strict
```

Do not guess `resourceVersion`; obtain it from the live GET when the target requires it.

## What to inspect

A successful HTTP status is necessary but not sufficient.

Inspect the returned resource and verify at least:

- `apiVersion` and `kind`
- `metadata.namespace == "default"` when present
- dashboard identity/name
- required variables and their types
- layout kind
- every `ElementReference.name` resolves to a returned `spec.elements` key
- every panel element is still `kind: "Panel"`
- no expected field disappeared because of conversion/defaulting
- no unexpected wrapper such as `layout.AutoGridLayoutKind`, `layout.spec.layout`, or `query.spec.query` appeared
- visualization plugin IDs remain the intended IDs

If the server returns warnings, capture and evaluate them. Unknown-field warnings are a review failure even if a non-strict request would otherwise succeed.

## When the dry-run fails

Do not infer a root cause from a single error line.

MUST read `knowledge/grafana/v2-validation-errors.md`, preserve the complete error details, classify the failure layer, and isolate the selected schema branch before recommending a correction.

In particular, Dashboard V2 layout is a CUE disjunction. An AutoGrid payload can report `conflicting values` for `GridLayout`, `RowsLayout`, and `TabsLayout` simply because those alternative branches do not match. Those messages do not prove that multiple layouts are present and do not prove that AutoGrid is unsupported. Find the error from the branch matching the submitted discriminator.

Do not add generated union-arm wrappers such as `AutoGridLayoutKind` to the Dashboard JSON based on OpenAPI/language-binding structure. The Dashboard V2 wire layout remains a flattened `{kind, spec}` object when that is what the target resource API emits/accepts.

If the matching-branch failure is not obvious, run the minimal target-side probe from `knowledge/grafana/v2-validation-errors.md` before changing the production dashboard source.

## Dry-run catches and does not catch

Dry-run is valuable for:

- target-version schema mismatches
- unknown fields when strict validation is enabled
- admission/conversion errors
- malformed V2 resource envelopes
- many invalid nested V2 shapes
- some server-side invariants that static JSON/schema checks miss

Dry-run is NOT a substitute for:

- live Prometheus query validation
- plugin inventory validation
- layout element-reference checks in the returned object
- real publication verification
- follow-up GET after an actual write

Current Grafana server code also skips some write-time checks during dry-run, including some folder existence/access and quota checks. Do not claim dry-run proves those behaviors. The target pinned implementation wins if it differs.

## Review result

The reviewer may return `PASS` only when all applicable checks pass, including server-side dry-run when target Grafana API access is available/required.

On failure, report the exact Grafana error concisely and point back to the Jsonnet/Grafonnet source correction. Do not patch the rendered JSON as the final fix. Do not replace unresolved evidence with a speculative compatibility explanation.
