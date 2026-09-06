# Publishing Grafana Dashboard Schema V2

Read this file only when the user asks to publish/write the dashboard or when an existing Dashboard V2 resource must be inspected through the Grafana API.

Only the fresh `dashboard-publisher` performs a real write. The coordinator routes the approved artifacts and checks the resulting publish report; it does not interpret Swagger or construct API payloads.

**MUST read `knowledge/security/output-redaction.md` before target access.**

## API contract

Do not guess Dashboard V2 API fields or routes.

Use the target Grafana Swagger/OpenAPI schema through the configured opaque target access. Do not print or copy the resolved endpoint into visible commands or output.

The target Grafana contract wins over local/general knowledge. If the target exposes another structured dashboard API version such as `v2beta1`, use the version advertised by that target and its Swagger/OpenAPI schema.

Do not convert a Schema V2 dashboard to classic dashboard JSON just to publish it. Do not use the legacy dashboard endpoint for a Schema V2 resource.

## Namespace

Always use the Grafana Dashboard resource namespace:

```text
default
```

Do not ask for, derive, discover, or configure another Dashboard resource namespace.

The Dashboard resource API namespace is not the Kubernetes namespace and is not the dashboard variable named `namespace`. Kubernetes namespace selection continues to use `$namespace`; publishing always uses `namespaces/default`.

## Resource API

For stable V2, use the target-advertised collection create, resource GET, and resource PUT operations under the Dashboard resource API.

Confirm methods and request schemas in the target Swagger before writing. Keep `namespaces/default` even when the target exposes another structured Dashboard API version.

`metadata.name` is the dashboard resource identity used by the item operation. Keep the literal identity inside the local request/artifact only; do not echo it in visible commands or completion output.

A create request is built from the rendered V2 dashboard spec plus resource metadata, for example:

```json
{
  "metadata": {
    "name": "<dashboard-name>",
    "annotations": {
      "grafana.app/folder": "<folder-uid>"
    }
  },
  "spec": {}
}
```

Populate `spec` with the rendered Dashboard Schema V2 spec. Omit the folder annotation when no folder is required.

If the rendered Jsonnet produces a full resource containing `apiVersion`, `kind`, `metadata`, and `spec`, use its `spec` as the dashboard spec and construct the API request according to the target Swagger. Do not blindly POST a DTO or classic dashboard envelope.

## Visible command discipline

All target-access commands are visible output unless the runtime explicitly guarantees otherwise.

- never paste the literal target endpoint into a command
- never paste a literal dashboard/resource identity into a command when an opaque variable/file can be used
- never assign the resolved sensitive value in the same visible command
- use configured opaque variables/wrappers and neutral request files
- keep response bodies in neutral scratch files and sanitize excerpts before surfacing them
- never enable shell tracing

If the request body contains target-identifying resource names or selectors, pass it with `--data-binary @<neutral-file>` or the equivalent local wrapper mechanism rather than echoing the JSON inline.

## Layout reference validation

Before publishing, verify every V2 layout element reference against the same rendered `spec.elements` map.

For every `ElementReference.name = X`, require an exact `spec.elements[X]` key. Do not translate the name to a UID and do not add a guessed UID field to normal panel elements.

Grafana may report a missing-panel error whose wording mentions a UID. Despite that wording, treat it as a missing/mismatched element-map key when the implementation resolves `elements[item.spec.element.name]`.

Read `knowledge/grafana/layout-reference-debugging.md` for concrete comparison commands. Sanitize any target identifiers before surfacing command output.

After publishing, perform the same comparison on the resource returned by Grafana. If the rendered request contained the element key but the stored resource does not, investigate the request envelope/API version rather than changing the layout reference model.

## Visualization plugin validation

Before publishing, validate every V2 panel visualization against the target/pinned Grafana environment.

Keep these fields separate:

- `spec.elements` map key: dashboard-local descriptive identifier
- panel element `kind`: normally `Panel`
- panel visualization plugin ID: normally `spec.vizConfig.group`

Never copy an element name, title, placement, metric name, or operational question into `vizConfig.group` unless independent target evidence proves a panel plugin with exactly that ID exists.

When target Grafana API access is available, inspect the installed plugin inventory through the configured opaque target access and require every used visualization plugin ID to resolve to an available panel plugin. Otherwise verify it from pinned Grafonnet constructors or local panel plugin schemas for the exact target version.

Do not print target endpoints or unrelated installed-resource identifiers while checking plugin inventory.

Do not publish when a visualization plugin ID is unknown or unverified. Dashboard schema validation alone is not proof that the referenced visualization plugin exists.

## Create versus update

Before publishing, determine whether the resource already exists under `namespaces/default`.

For an existing dashboard:

1. GET the current resource through the opaque configured access.
2. Preserve its resource identity and folder placement unless the user requested a change.
3. Preserve or send server metadata such as `resourceVersion` only when required by the target API contract.
4. Replace it with the method/body defined by the target Swagger, normally the item update operation.

For a new dashboard, use the target-advertised collection create operation under `namespaces/default`.

Never create a second dashboard merely because an update failed. Report conflicts, authorization failures, schema-validation errors, missing element references, and missing panel plugins instead, with sensitive target literals removed.

## Authentication

Use only the configured writable Grafana authentication method. Do not print tokens, credentials, `.netrc` contents, authorization headers, session data, or resolved endpoint values in agent output.

Read-only Prometheus datasource access and writable Grafana dashboard API access are separate capabilities. Publishing requires the latter.

## Publish order

Publish only after:

1. Jsonnet source is formatted.
2. Dashboard renders successfully.
3. Rendered JSON parses.
4. Local schema/lint checks available in the repository pass.
5. Every V2 layout `ElementReference.name` resolves to an exact `spec.elements` key.
6. Every V2 panel visualization plugin ID is verified.
7. `promql-reviewer` has approved every query in the exact current query pack, with live validation when datasource access exists.
8. Confidentiality/output-redaction checks pass.
9. `dashboard-reviewer` has returned `PASS` for the exact current build/candidate digests. Fixing a finding requires rebuilding and repeating review; the fix alone is not approval.
10. The exact reviewed candidate has been mechanically promoted and its final-path render is byte-identical to the reviewed render.

## Verification

A successful write response is not enough.

After create/update:

1. GET the dashboard resource from the same API version under `namespaces/default` through opaque access.
2. Verify the returned resource namespace is `default`.
3. Verify resource identity/folder placement locally without printing their literal values.
4. Verify `spec.title` and required variables.
5. Re-check every layout `ElementReference.name` against the returned `spec.elements` keys.
6. Verify the expected V2 layout and required variables are present in the returned `spec`.
7. Verify the returned panel visualization plugin IDs are the expected verified IDs.
8. Report only the API version and sanitized verification status, not the target endpoint or resource identity.

Do not claim publication succeeded if the follow-up read fails, returns a different resource, returns a non-default resource namespace, contains a broken element reference, or contains an unverified visualization plugin ID.
