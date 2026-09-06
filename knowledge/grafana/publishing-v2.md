# Publishing Grafana Dashboard Schema V2

Read this file only when the user asks to publish/write the dashboard or when an existing Dashboard V2 resource must be inspected through the Grafana API.

## API contract

Do not guess Dashboard V2 API fields or routes.

Use the target Grafana Swagger first:

```text
<GRAFANA_URL>/swagger?api=dashboard.grafana.app-v2
```

Public reference:

```text
https://play.grafana.org/swagger?api=dashboard.grafana.app-v2
```

The target Grafana contract wins over the public reference. If the target exposes another structured dashboard API version such as `v2beta1`, use the version advertised by that target and its Swagger/OpenAPI schema.

Do not convert a Schema V2 dashboard to classic dashboard JSON just to publish it. Do not use the legacy `/api/dashboards/db` endpoint for a Schema V2 resource.

## Namespace

Always use the Grafana Dashboard resource namespace:

```text
default
```

Do not ask for, derive, discover, or configure another Dashboard resource namespace.

The Dashboard resource API namespace is not the Kubernetes namespace and is not the dashboard variable named `namespace`. Kubernetes namespace selection continues to use `$namespace`; publishing always uses `namespaces/default`.

## Resource API

For the stable V2 API, the resource routes are:

```text
POST /apis/dashboard.grafana.app/v2/namespaces/default/dashboards
GET  /apis/dashboard.grafana.app/v2/namespaces/default/dashboards/<name>
PUT  /apis/dashboard.grafana.app/v2/namespaces/default/dashboards/<name>
```

Confirm these methods and request schemas in the target Swagger before writing. Keep `namespaces/default` even when the target exposes another structured Dashboard API version.

`metadata.name` is the dashboard resource name/UID used in the item URL.

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

## Layout reference validation

Before publishing, verify every V2 layout element reference against the same rendered `spec.elements` map.

For every `ElementReference.name = X`, require an exact `spec.elements[X]` key. Do not translate the name to a UID and do not add a guessed UID field to normal panel elements.

Grafana may report:

```text
Panel with uid <name> not found in the dashboard elements
```

Despite that wording, Grafana's AutoGrid implementation looks up `elements[item.spec.element.name]`. Treat this as a missing/mismatched element-map key.

Read `knowledge/grafana/layout-reference-debugging.md` for concrete comparison commands.

After publishing, perform the same comparison on the resource returned by Grafana. If the rendered request contained the element key but the stored resource does not, investigate the request envelope/API version rather than changing the layout reference model.

## Visualization plugin validation

Before publishing, validate every V2 panel visualization against the target/pinned Grafana environment.

Keep these fields separate:

- `spec.elements` map key: dashboard-local descriptive identifier; arbitrary names such as `overview-mean-pages` are allowed
- panel element `kind`: normally `Panel`
- panel visualization plugin ID: normally `spec.vizConfig.group`

Never copy an element name, title, placement, metric name, or operational question into `vizConfig.group` unless independent target evidence proves a panel plugin with exactly that ID exists.

When target Grafana API access is available, inspect the installed plugin inventory, for example with `GET /api/plugins`, and require every used visualization plugin ID to resolve to an available panel plugin. Otherwise verify it from pinned Grafonnet constructors or local panel plugin schemas for the exact target version.

Do not publish when a visualization plugin ID is unknown or unverified. Dashboard schema validation alone is not proof that the referenced visualization plugin exists.

## Create versus update

Before publishing, determine whether the resource already exists under `namespaces/default`.

For an existing dashboard:

1. `GET` the current resource from `namespaces/default`.
2. Preserve its `metadata.name` and folder placement unless the user requested a change.
3. Preserve or send server metadata such as `resourceVersion` only when required by the target API contract.
4. Replace it with the method and body defined by the target Swagger, normally `PUT` on the item URL.

For a new dashboard, use the collection create operation under `namespaces/default`, normally `POST`.

Never create a second dashboard merely because an update failed. Report conflicts, authorization failures, schema-validation errors, missing element references, and missing panel plugins instead.

## Authentication

Use only the configured writable Grafana authentication method. Do not print tokens, credentials, `.netrc` contents, or authorization headers in agent output.

Read-only Prometheus datasource access and writable Grafana dashboard API access are separate capabilities. Publishing requires the latter.

## Publish order

Publish only after:

1. Jsonnet source is formatted.
2. Dashboard renders successfully.
3. Rendered JSON parses.
4. Local schema/lint checks available in the repository pass.
5. Every V2 layout `ElementReference.name` resolves to an exact `spec.elements` key.
6. Every V2 panel visualization plugin ID is verified.
7. Representative live queries are validated when datasource access exists.
8. `dashboard-reviewer` passes or its confirmed findings are fixed.

## Verification

A successful write response is not enough.

After create/update:

1. `GET` the dashboard resource from the same API version under `namespaces/default`.
2. Verify the returned resource namespace is `default`.
3. Verify `metadata.name`, folder annotation when applicable, and `spec.title`.
4. Re-check every layout `ElementReference.name` against the returned `spec.elements` keys.
5. Verify the expected V2 layout and required variables are present in the returned `spec`.
6. Verify the returned panel visualization plugin IDs are the expected verified IDs.
7. Report the returned resource name and API version.

Do not claim publication succeeded if the follow-up read fails, returns a different resource, returns a non-default resource namespace, contains a broken element reference, or contains an unverified visualization plugin ID.
