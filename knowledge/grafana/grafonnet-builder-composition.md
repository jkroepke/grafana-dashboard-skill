# Grafonnet V2 builder composition

Read this file before composing Dashboard Schema V2 builders.

The generated Grafonnet API is **path-oriented**. Not every nested builder returns a standalone object of the type named by its namespace. Determine what a builder returns from its generated function body.

## Hard rule

- MUST use generated builders when available.
- MUST inspect the pinned local generated function body when composition is unclear.
- MUST NOT feed a path-mixin result back into a parent `withX(...)` setter when that result already contains the parent path.
- MUST NOT replace a confusing builder with hand-written JSON merely to avoid understanding its composition.
- MUST NOT infer a field name from a classic dashboard model or from model memory when the pinned V2 builder exposes a different field.
- Render a small isolated expression when necessary to prove the resulting shape before integrating it.
- For Grafonnet v13, use the canonical recipes below before inventing another composition pattern.

## Canonical Grafonnet v13 recipes

These examples are intentionally concrete. Copy their composition pattern, then replace only application-specific values.

The pinned local generated API remains authoritative if the repository moves away from v13.

### Dashboard root

```jsonnet
local g = import 'github.com/grafana/grafonnet/gen/grafonnet-latest/main.libsonnet';
local d = g.apps.dashboard.v2;

d.new('my-dashboard', 'My Dashboard')
+ d.spec.withDescription('Operational dashboard')
+ d.spec.withEditable(false)
+ d.spec.withTags(['application'])
```

Do not hand-write the `apiVersion`, `kind`, `metadata`, and root `spec` when `d.new(...)` and generated root builders exist.

### Time settings

`d.spec.timeSettings.*` methods are dashboard path mixins. Add them directly to the dashboard:

```jsonnet
d.new('my-dashboard', 'My Dashboard')
+ d.spec.timeSettings.withFrom('now-6h')
+ d.spec.timeSettings.withTo('now')
+ d.spec.timeSettings.withTimezone('browser')
```

Do not wrap those fragments in `d.spec.withTimeSettings(...)`.

### Datasource variable

For Grafonnet v13, the datasource variable identifies the datasource plugin through `pluginId`:

```jsonnet
local dv = d.spec.variables.DatasourceVariableKind;

local datasourceVar =
  dv.withKind()
  + dv.spec.withName('datasource')
  + dv.spec.withLabel('Data source')
  + dv.spec.withPluginId('prometheus')
  + dv.spec.withIncludeAll(false)
  + dv.spec.withMulti(false)
  + dv.spec.withRefresh('never')
  + dv.spec.withHide('dontHide');
```

Do not substitute `dv.spec.withQuery('prometheus')` for `withPluginId('prometheus')` on v13.

### Namespace query variable

The QueryVariable builder is a standalone collection item. Its nested `spec.query.*` methods are path mixins within that variable.

```jsonnet
local qv = d.spec.variables.QueryVariableKind;

local namespaceVar =
  qv.withKind()
  + qv.spec.withName('namespace')
  + qv.spec.withLabel('Namespace')
  + qv.spec.withDescription('Application namespace')
  + qv.spec.withIncludeAll(false)
  + qv.spec.withMulti(false)
  + qv.spec.withRefresh('onDashboardLoad')
  + qv.spec.query.withKind()
  + qv.spec.query.withGroup('prometheus')
  + qv.spec.query.datasource.withName('<verified datasource-variable reference>')
  + qv.spec.query.withSpec({
      expr: 'label_values(<verified_application_metric>, kubernetes_namespace)',
    });
```

Do not create a `query` local from `qv.spec.query.*` and then feed it into `qv.spec.withQuery(query)`. The nested builders already write to `spec.query`.

### Pod query variable

```jsonnet
local podVar =
  qv.withKind()
  + qv.spec.withName('pod')
  + qv.spec.withLabel('Pod')
  + qv.spec.withDescription('Application pods')
  + qv.spec.withIncludeAll(true)
  + qv.spec.withAllValue('')
  + qv.spec.withMulti(true)
  + qv.spec.withRefresh('onDashboardLoad')
  + qv.spec.query.withKind()
  + qv.spec.query.withGroup('prometheus')
  + qv.spec.query.datasource.withName('<verified datasource-variable reference>')
  + qv.spec.query.withSpec({
      expr: 'label_values(<verified_application_metric>{kubernetes_namespace="$namespace"}, kubernetes_pod_name)',
    });
```

Keep `namespace` before `pod` in the dashboard variable list:

```jsonnet
d.spec.withVariables([
  datasourceVar,
  namespaceVar,
  podVar,
])
```

### AutoGrid layout item

```jsonnet
local auto = d.spec.layout.AutoGridLayoutKind;
local item = auto.spec.items;

local layoutItem(name) =
  item.withKind()
  + item.spec.element.withKind()
  + item.spec.element.withName(name);
```

The result is a standalone `AutoGridLayoutItem` suitable for `auto.spec.withItems(...)`.

### AutoGrid layout

The AutoGrid kind/spec builders are dashboard path mixins. Compose them directly into the dashboard:

```jsonnet
local elementNames = [
  'overview-mean-pages',
  'overview-errors',
];

d.new('my-dashboard', 'My Dashboard')
+ d.spec.withElements(elements)
+ auto.withKind()
+ auto.spec.withFillScreen(false)
+ auto.spec.withMaxColumnCount(3)
+ auto.spec.withItems([layoutItem(name) for name in elementNames])
```

Do not do this:

```jsonnet
local layout =
  auto.withKind()
  + auto.spec.withItems(items);

d.spec.withLayout(layout)  // WRONG for these v13 path mixins
```

### Annotation query

`d.spec.annotations` is a standalone annotation-item builder. Compose its nested query mixins directly into the annotation, then pass the complete annotation to `d.spec.withAnnotations(...)`.

```jsonnet
local annotation = d.spec.annotations;

local restartAnnotation =
  annotation.withKind()
  + annotation.spec.withBuiltIn(false)
  + annotation.spec.withName('Observed process restart')
  + annotation.spec.withEnable(true)
  + annotation.spec.withHide(false)
  + annotation.spec.query.withKind()
  + annotation.spec.query.withGroup('prometheus')
  + annotation.spec.query.datasource.withName('<verified datasource-variable reference>')
  + annotation.spec.query.withSpec({
      expr: 'changes(process_start_time_seconds{kubernetes_namespace="$namespace",kubernetes_pod_name=~"${pod:regex}"}[<validated-window>]) > 0',
    });

d.spec.withAnnotations([restartAnnotation])
```

Do not create a query fragment from `annotation.spec.query.*` and feed that fragment back into `annotation.spec.withQuery(...)`.

### Allowed raw-object exception: V2 panel elements

Grafonnet v13 does not expose a typed `PanelKind` / `QueryGroup` constructor under `g.apps.dashboard.v2`.

A schema-shaped V2 panel object is therefore allowed for the panel internals, but it MUST render as a V2 `PanelKind`:

```jsonnet
local panel = {
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
                datasource: { name: '<verified datasource reference>' },
                spec: {
                  expr: '<verified PromQL>',
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
};
```

Do not put `g.panel.stat.new(...)`, `g.panel.timeSeries.new(...)`, `g.panel.heatmap.new(...)`, or another classic panel object directly into V2 `spec.elements`.

### Minimal complete composition skeleton

Use this as the starting shape for a new v13 Schema V2 dashboard:

```jsonnet
local g = import 'github.com/grafana/grafonnet/gen/grafonnet-latest/main.libsonnet';
local d = g.apps.dashboard.v2;
local dv = d.spec.variables.DatasourceVariableKind;
local qv = d.spec.variables.QueryVariableKind;
local auto = d.spec.layout.AutoGridLayoutKind;
local item = auto.spec.items;

local datasourceVar =
  dv.withKind()
  + dv.spec.withName('datasource')
  + dv.spec.withLabel('Data source')
  + dv.spec.withPluginId('prometheus')
  + dv.spec.withIncludeAll(false)
  + dv.spec.withMulti(false);

local namespaceVar =
  qv.withKind()
  + qv.spec.withName('namespace')
  + qv.spec.withLabel('Namespace')
  + qv.spec.withIncludeAll(false)
  + qv.spec.withMulti(false)
  + qv.spec.query.withKind()
  + qv.spec.query.withGroup('prometheus')
  + qv.spec.query.datasource.withName('<verified datasource-variable reference>')
  + qv.spec.query.withSpec({ expr: '<namespace query>' });

local podVar =
  qv.withKind()
  + qv.spec.withName('pod')
  + qv.spec.withLabel('Pod')
  + qv.spec.withIncludeAll(true)
  + qv.spec.withAllValue('')
  + qv.spec.withMulti(true)
  + qv.spec.query.withKind()
  + qv.spec.query.withGroup('prometheus')
  + qv.spec.query.datasource.withName('<verified datasource-variable reference>')
  + qv.spec.query.withSpec({ expr: '<pod query>' });

local elementNames = ['overview'];
local elements = {
  overview: <schema-shaped V2 PanelKind>,
};

local layoutItem(name) =
  item.withKind()
  + item.spec.element.withKind()
  + item.spec.element.withName(name);

d.new('my-dashboard', 'My Dashboard')
+ d.spec.withDescription('Operational dashboard')
+ d.spec.withEditable(false)
+ d.spec.withElements(elements)
+ d.spec.withVariables([datasourceVar, namespaceVar, podVar])
+ d.spec.timeSettings.withFrom('now-6h')
+ d.spec.timeSettings.withTo('now')
+ auto.withKind()
+ auto.spec.withFillScreen(false)
+ auto.spec.withMaxColumnCount(3)
+ auto.spec.withItems([layoutItem(name) for name in elementNames])
```

## Two important builder shapes

### 1. Path mixins

A path mixin returns a fragment already rooted at its owning object path.

For Grafonnet v13, `d.spec.layout.AutoGridLayoutKind.*` and `d.spec.timeSettings.*` contain dashboard path mixins. Add those fragments directly to the dashboard resource.

### 2. Standalone collection-item builders

Some nested namespaces build standalone values intended for a parent array or map.

Examples:

- `d.spec.variables.QueryVariableKind.withKind()` -> standalone variable object
- `d.spec.variables.DatasourceVariableKind.withKind()` -> standalone variable object
- `d.spec.layout.AutoGridLayoutKind.spec.items.withKind()` -> standalone AutoGrid item
- `d.spec.annotations.withKind()` -> standalone annotation item

Compose their nested path mixins into that standalone object, then pass the completed item to the corresponding parent collection setter.

## How to classify an unfamiliar builder

Read the generated function body.

If it returns something like:

```jsonnet
{
  spec+: {
    layout+: {
      spec+: { fillScreen: value },
    },
  },
}
```

it is a dashboard path mixin.

If it returns something like:

```jsonnet
{ kind: 'QueryVariable' }
```

or:

```jsonnet
{ kind: 'AutoGridLayoutItem' }
```

it is a standalone value builder.

If it returns:

```jsonnet
{ spec+: { query+: { kind: 'DataQuery' } } }
```

it is a path mixin relative to the standalone parent object, not a standalone `DataQuery`.

## Never use both composition routes

For one field, choose exactly one of these:

1. compose generated path mixins directly into the owning object, or
2. pass a true standalone inner value to the parent's `withX(value)` setter.

Do not combine both routes for the same field.

Suspicious examples that require correction or proof from the generated body:

```jsonnet
d.spec.withLayout(d.spec.layout.AutoGridLayoutKind.withKind() + ...)
qv.spec.withQuery(qv.spec.query.withKind() + ...)
d.spec.withTimeSettings(d.spec.timeSettings.withFrom('now-6h') + ...)
item.spec.withElement(item.spec.element.withKind() + ...)
```

## Validation

Before integrating a complicated builder chain, render the smallest possible fixture and inspect the resulting shape.

For AutoGrid, require:

```json
{
  "spec": {
    "layout": {
      "kind": "AutoGridLayout",
      "spec": {
        "items": []
      }
    }
  }
}
```

There must be no extra `layout.spec.layout`, `layout.AutoGridLayoutKind`, `query.spec.query`, or other duplicate wrapper introduced by builder misuse.

The reviewer must `FAIL` source that double-wraps generated path mixins, even if Jsonnet renders successfully.
