# Grafana Dashboard V2 server-side dry-run validation

Read this file when reviewing a rendered Dashboard Schema V2 resource against a real Grafana instance.

## Purpose

Use Grafana's own Dashboard resource API as a final schema/admission check before the reviewer can return `PASS`.

This is validation only. A dry-run request MUST NOT be treated as publication.

## Hard rule

When target Grafana dashboard API access is configured:

- the reviewer MUST submit the rendered Dashboard resource to the real target Grafana using the target-advertised dry-run mechanism
- the reviewer MUST use the Dashboard resource namespace `default`
- the reviewer MUST use the exact structured API version advertised by the target Swagger
- the reviewer MUST enable strict field validation when the target advertises it
- the reviewer MUST NOT return `PASS` if the dry-run request fails
- the reviewer MUST inspect the dry-run response body, not only the HTTP status
- on any dry-run failure, the reviewer MUST read `knowledge/grafana/v2-validation-errors.md` before changing or recommending a source change
- credentials and authorization headers MUST NOT be printed in review output

If the target Swagger exposes no dry-run mechanism, return `FAIL` with the validation gap unless the task explicitly permits server-side validation to remain unverified.

## Source of truth

The coordinator's run contract must first contain the cached V2 OpenAPI
capability result. The coordinator obtains it by executing the configured local
access command, which reaches this discovery document without receiving the
target URL as an argument:

```text
<GRAFANA_URL>/openapi/v3/apis/dashboard.grafana.app/v2
```

Use the target-advertised operations and schemas from that document. It is a
one-time coordinator discovery check, not a replacement for this reviewer's
dry-run. Do not rediscover it in this stage or bypass the configured local
command with direct network access. If a target supplies only an opaque Swagger
wrapper, use that target-advertised contract after the run contract records the
resulting capability gap; never guess a route or API version.

If the target uses another structured version such as `v2beta1`, use that target version instead.

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

unless the target Swagger explicitly says that is valid. Current stable V2 documents `All` as the valid dry-run directive.

Also use strict field validation when advertised:

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

When diagnosing a failure, use equivalent options that preserve the complete response body and headers even on an HTTP error. See `knowledge/grafana/v2-validation-errors.md`.

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

On failure, report the exact Grafana error concisely and point back to the Jsonnet/Grafonnet source correction. Do not patch the rendered JSON as the final fix. Do not replace unresolved evidence with a speculative server/version explanation.
