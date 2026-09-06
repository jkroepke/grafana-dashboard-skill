# Grafonnet and Dashboard Schema V2

Use this file whenever creating or reviewing a Dashboard Schema V2 dashboard with Grafonnet.

This repository targets an air-gapped model. Do not rely on model memory for Grafonnet APIs. The vendored/pinned Grafonnet source is authoritative.

## Hard rule: use builders when available

For Dashboard Schema V2, generated Grafonnet builders are mandatory when the pinned local library provides them.

- **MUST use the pinned generated Grafonnet builder when one exists.**
- **MUST NOT hand-author an equivalent raw Jsonnet/JSON object just because the schema shape is known.**
- **MUST inspect the vendored generated API before claiming that no builder exists.**
- **MUST preserve the repository's pinned Grafonnet version/import convention.**
- Raw schema-shaped Jsonnet is allowed only when the pinned Grafonnet API genuinely has no suitable builder, or when the repository documents a compatibility workaround for that exact pin.
- A manual equivalent of an available builder is a correctness failure, not a style preference.
- Successful Jsonnet rendering does not excuse bypassing an available builder.
- Do not patch rendered JSON to compensate for incorrect source construction.

The reviewer must return `FAIL` when an available generated V2 builder is bypassed without a documented compatibility reason.

### Documented Grafonnet v13 nested query-spec exception

In the documented v13 generated API, both `QueryVariableKind.spec.query.withSpec(...)` and `annotations.spec.query.withSpec(...)` emit `query.spec` at the standalone item's root. The required Dashboard V2 location is `spec.query.spec`.

For this exact pin:

- use generated builders for the variable/annotation, query kind, group, and datasource
- manually merge only the datasource-specific query `spec` into `{ spec+: { query+: { spec: ... } } }`
- use the Prometheus variable-query fields `qryType`, `query`, and `refId` for `QueryVariable`
- use the normal Prometheus query field `expr` for panel and annotation queries
- inspect the rendered JSON to confirm the final location and payload

This is a documented compatibility exception, not permission to hand-author other generated V2 structures. Read `knowledge/grafana/grafonnet-builder-composition.md` for the complete recipes.

## Resolve the actual Grafonnet version

The import path may legitimately use the upstream alias:

```jsonnet
local grafonnet = import 'github.com/grafana/grafonnet/gen/grafonnet-latest/main.libsonnet';
```

Do not reject `grafonnet-latest` merely because its name says `latest`. With jsonnet-bundler it is a vendored import path and the dependency is normally pinned by the repository lock file.

Inspect the local alias and lock before making version claims:

```bash
cat vendor/github.com/grafana/grafonnet/gen/grafonnet-latest/main.libsonnet
rg -n 'grafonnet' jsonnetfile.json jsonnetfile.lock.json
```

At the Grafonnet snapshot used when this guidance was written, `gen/grafonnet-latest/main.libsonnet` forwards to `gen/grafonnet-v13.0.0/main.libsonnet`. Do not assume this mapping for another pin; inspect the local vendored file.

Preserve the repository's existing import convention and pin. Do not rewrite `grafonnet-latest` to a versioned path solely for style.

## Classic dashboard API versus Dashboard V2 resource API

These are different Grafonnet surfaces.

Classic dashboard JSON:

```jsonnet
local g = import 'github.com/grafana/grafonnet/gen/grafonnet-latest/main.libsonnet';

g.dashboard.new('My Dashboard')
```

Dashboard Schema V2 resource:

```jsonnet
local g = import 'github.com/grafana/grafonnet/gen/grafonnet-latest/main.libsonnet';
local d = g.apps.dashboard.v2;

d.new('my-dashboard', 'My Dashboard')
```

For the v13 generated API, `d.new(name, title)` produces the resource envelope with:

```json
{
  "apiVersion": "dashboard.grafana.app/v2",
  "kind": "Dashboard",
  "metadata": {"name": "my-dashboard"},
  "spec": {"title": "My Dashboard"}
}
```

Do not use `g.dashboard.new(...)` as the root of a Dashboard Schema V2 resource.

## Generated V2 builders

For Grafonnet v13, `g.apps.dashboard.v2` includes generated builders for the dashboard resource and many V2 structures, including:

- `new(name, title)`
- `metadata.*`
- `spec.withElements(...)` / `spec.withElementsMixin(...)`
- `spec.withAnnotations(...)`
- `spec.withVariables(...)`
- `spec.timeSettings.*`
- `spec.layout.AutoGridLayoutKind.*`
- `spec.layout.GridLayoutKind.*`
- `spec.layout.RowsLayoutKind.*`
- `spec.layout.TabsLayoutKind.*`
- typed layout-item builders under each layout kind
- typed V2 variable builders under `spec.variables.*`
- typed annotation builders under `spec.annotations.*`

These builders are mandatory when present.

When unsure, inspect the pinned local generated API instead of guessing:

```bash
rg -n 'withElements|AutoGridLayoutKind|DatasourceVariableKind|QueryVariableKind|AnnotationQuery' \
  vendor/github.com/grafana/grafonnet/gen/grafonnet-v*/apps/dashboard/v2.libsonnet
```

The local vendored revision wins over examples in this file.

## Allowed exception: V2 panel elements

Do not generalize the builder rule into "every V2 object has a typed builder".

In Grafonnet v13, the generated Dashboard V2 API accepts `spec.withElements(value)` as an object map, but it does not provide a typed `PanelKind`/`QueryGroup` constructor under `g.apps.dashboard.v2`.

Therefore a schema-shaped Jsonnet object is appropriate for a V2 panel element when no repository helper exists.

A V2 panel element is structurally like:

```jsonnet
{
  kind: 'Panel',
  spec: {
    id: 1,
    title: 'Example',
    data: {
      kind: 'QueryGroup',
      spec: {
        queries: [
          {
            kind: 'PanelQuery',
            spec: {
              refId: 'A',
              query: {
                kind: 'DataQuery',
                group: 'prometheus',
                datasource: { name: '${datasource}' },
                spec: {
                  expr: '<promql>',
                },
              },
              hidden: false,
            },
          },
        ],
      },
    },
    vizConfig: {
      kind: 'VizConfig',
      group: 'timeseries',
      spec: {
        fieldConfig: {
          defaults: {},
          overrides: [],
        },
        options: {},
      },
    },
  },
}
```

This is a structural example, not a license to guess required fields, versions, plugin options, or query properties. Check the pinned Grafana V2 schema and target Grafana for the exact fields required by the local version.

## Do not put classic panel objects directly in V2 elements

`g.panel.stat.new(...)`, `g.panel.timeSeries.new(...)`, `g.panel.heatmap.new(...)`, and the other `g.panel.*` builders create the classic panel representation.

Their model uses classic panel fields such as plugin `type`, `datasource`, `targets`, `fieldConfig`, and `options` on the panel object.

Dashboard V2 `spec.elements` expects values such as `PanelKind` with `kind: 'Panel'` and a nested V2 `spec` containing `data` and `vizConfig`.

Therefore this is wrong for a Schema V2 dashboard:

```jsonnet
local elements = {
  'overview-mean-pages':
    g.panel.stat.new('Mean pages')
    + g.panel.stat.queryOptions.withTargets([...]),
};

// later: d.spec.withElements(elements)
```

A Jsonnet render succeeding does not make that element a valid V2 `PanelKind`.

Do not patch the rendered JSON to compensate. Fix the Jsonnet source.

If the repository has a local helper that intentionally converts classic panel objects into V2 `PanelKind`, inspect and use that helper. Do not invent such a conversion.

## V2 query wrappers are not classic target objects

Do not confuse `g.query.prometheus` with a complete V2 panel query.

A V2 panel query has wrapper layers:

```text
QueryGroup
  -> PanelQuery
    -> DataQuery
      -> Prometheus query spec
```

The V2 `DataQuery` carries plugin identity separately, for example:

```jsonnet
{
  kind: 'DataQuery',
  group: 'prometheus',
  datasource: { name: '${datasource}' },
  spec: {
    expr: '<promql>',
  },
}
```

Classic datasource references such as:

```json
{"type": "prometheus", "uid": "${datasource}"}
```

must not be assumed to be the V2 `DataQuery.datasource` shape. In Dashboard V2 the datasource reference is represented by `name` in the schema used by Grafana v13.

Use `g.query.prometheus` only where its rendered object is valid for the exact plugin-specific `DataQuery.spec` required by the pinned V2 schema. Do not use a classic query target as the whole `PanelQuery` or `DataQuery`.

## AutoGrid construction

Use the generated V2 layout builders. For v13, the relevant namespaces are:

```jsonnet
local d = g.apps.dashboard.v2;
local auto = d.spec.layout.AutoGridLayoutKind;
local item = auto.spec.items;
```

A layout item reference must be built from the generated item API when that API exists:

```jsonnet
local elementName = 'overview-mean-pages';

local layoutItem =
  item.withKind()
  + item.spec.element.withKind()
  + item.spec.element.withName(elementName);
```

Use the same `elementName` as the key in the elements map:

```jsonnet
local elements = {
  [elementName]: panel,
};
```

Then compose the V2 dashboard with generated builders, for example:

```jsonnet
d.new('my-dashboard', 'My Dashboard')
+ d.spec.withElements(elements)
+ auto.withKind()
+ auto.spec.withItems([layoutItem])
```

Do not manually write `{kind: 'AutoGridLayoutItem', ...}` or `{kind: 'ElementReference', ...}` when the pinned generated builder exists.

## Variables, annotations, and time settings

MUST use the generated V2 builders under these namespaces when available:

```text
d.spec.variables.*
d.spec.annotations.*
d.spec.timeSettings.*
```

Do not copy classic dashboard variable or annotation DTO shapes into a V2 resource.

For query variables and annotations, remember that their query is a V2 `DataQuery`. Verify `kind`, `group`, `datasource`, and plugin-specific `spec` against the pinned generated API/schema.

## Source review checklist

Before accepting a Schema V2 Grafonnet source:

1. Resolve the actual vendored Grafonnet revision/alias.
2. Confirm the root uses `g.apps.dashboard.v2` rather than the classic `g.dashboard` API.
3. **FAIL if an available generated V2 builder is replaced by a hand-authored equivalent without a documented compatibility reason.**
4. Use generated V2 builders for envelope/layout/variables/annotations/time settings when available.
5. Require every `spec.elements` panel value to render as `kind: "Panel"` with a V2 `spec`.
6. Reject direct `g.panel.*.new(...)` objects inside V2 `spec.elements` unless a verified conversion helper wraps them.
7. Require V2 panels to use `data.kind = "QueryGroup"` and `vizConfig.kind = "VizConfig"` where required by the pinned schema.
8. Require V2 DataQuery plugin identity/datasource fields to use the pinned V2 shape; do not assume classic `{type, uid}` datasource references.
9. Require every layout `ElementReference.name` to exactly match a key in rendered `spec.elements`.
10. Render and inspect the resulting JSON; source-level builder use alone is not sufficient.
11. Validate the rendered resource against the target/pinned Dashboard V2 schema before publishing.
