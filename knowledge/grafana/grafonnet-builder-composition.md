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

## Two important builder shapes

### 1. Path mixins

A path mixin returns a fragment already rooted at its owning object path.

For Grafonnet v13, these AutoGrid builders are dashboard path mixins:

```jsonnet
local d = g.apps.dashboard.v2;
local auto = d.spec.layout.AutoGridLayoutKind;

auto.withKind()
auto.spec.withFillScreen(false)
auto.spec.withMaxColumnCount(3)
auto.spec.withItems(items)
```

The generated bodies already write into `spec.layout` / `spec.layout.spec`.

Therefore compose them **directly onto the dashboard resource**:

```jsonnet
local d = g.apps.dashboard.v2;
local auto = d.spec.layout.AutoGridLayoutKind;
local item = auto.spec.items;

local layoutItem(name) =
  item.withKind()
  + item.spec.element.withKind()
  + item.spec.element.withName(name);

d.new('my-dashboard', 'My Dashboard')
+ d.spec.withElements(elements)
+ auto.withKind()
+ auto.spec.withFillScreen(false)
+ auto.spec.withMaxColumnCount(3)
+ auto.spec.withItems([
    layoutItem('overview-mean-pages'),
    layoutItem('overview-errors'),
  ])
```

Do **not** do this:

```jsonnet
local layout =
  auto.withKind()
  + auto.spec.withItems(items);

d.new('my-dashboard', 'My Dashboard')
+ d.spec.withLayout(layout)  // WRONG: layout is already rooted at spec.layout
```

Do not extract `layout.spec.layout` merely to feed it into `withLayout(...)`. Use one composition route.

The same principle applies to dashboard path builders such as `d.spec.timeSettings.*`: when the generated method already writes into `spec.timeSettings`, add that mixin directly to the dashboard instead of wrapping it again with `d.spec.withTimeSettings(...)`.

### 2. Standalone collection-item builders

Some nested namespaces build standalone values intended for an array or map.

For example, `d.spec.variables.QueryVariableKind.withKind()` returns a standalone variable object beginning with:

```json
{"kind":"QueryVariable"}
```

Compose its nested path mixins into that standalone variable, then pass the completed variable to `d.spec.withVariables(...)`:

```jsonnet
local d = g.apps.dashboard.v2;
local qv = d.spec.variables.QueryVariableKind;

local namespaceVar =
  qv.withKind()
  + qv.spec.withName('namespace')
  + qv.spec.withLabel('Namespace')
  + qv.spec.withIncludeAll(false)
  + qv.spec.withMulti(false)
  + qv.spec.withRefresh('onDashboardLoad')
  + qv.spec.query.withKind()
  + qv.spec.query.withGroup('prometheus')
  + qv.spec.query.datasource.withName('<verified datasource reference>')
  + qv.spec.query.withSpec({
      expr: '<verified variable query>',
    });

d.new('my-dashboard', 'My Dashboard')
+ d.spec.withVariables([namespaceVar])
```

The nested query builders above are **path mixins within the QueryVariable object**. They already write under `spec.query`.

Therefore do **not** do this:

```jsonnet
local query =
  qv.spec.query.withKind()
  + qv.spec.query.withGroup('prometheus')
  + qv.spec.query.withSpec({ expr: '...' });

local namespaceVar =
  qv.withKind()
  + qv.spec.withQuery(query);  // WRONG: query already contains spec.query
```

If a standalone `DataQuery` value is genuinely required by a parent setter, construct it only with a builder that actually returns a standalone `DataQuery`, or use the documented schema-shaped exception when the pinned API has no such standalone builder. Do not mistake a nested path mixin for a standalone value.

## Canonical DatasourceVariable builder

Do not copy the classic datasource-variable model or guess a `query` field.

For Grafonnet v13, `DatasourceVariableKind.spec` exposes `withPluginId(...)`. Use the pinned generated field:

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

Then include it through:

```jsonnet
d.spec.withVariables([datasourceVar, namespaceVar, podVar])
```

For the v13 `DatasourceVariableKind`, do **not** substitute:

```jsonnet
dv.spec.withQuery('prometheus')
```

for `withPluginId('prometheus')`. Verify the exact builder fields again if the pinned Grafonnet revision changes.

## AutoGrid item builders

`d.spec.layout.AutoGridLayoutKind.spec.items` is a standalone item builder namespace.

This is correct:

```jsonnet
local item = d.spec.layout.AutoGridLayoutKind.spec.items;

local x =
  item.withKind()
  + item.spec.element.withKind()
  + item.spec.element.withName('overview-mean-pages');
```

It produces an `AutoGridLayoutItem` value that can be passed to `auto.spec.withItems(...)`.

The element reference is built by composing `item.spec.element.*` directly into the item. Do not separately wrap that fragment again with `item.spec.withElement(...)`.

## Annotation builders

`d.spec.annotations` builds a standalone `AnnotationQuery` item. Compose `annotations.withKind()` with its `annotations.spec.*` and nested query path mixins, then pass the completed item to `d.spec.withAnnotations(...)`.

Do not build a nested annotation query path fragment and then pass the wrapped fragment back to `annotations.spec.withQuery(...)`.

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

it is a dashboard path mixin. Add it directly to the dashboard resource.

If it returns something like:

```jsonnet
{ kind: 'QueryVariable' }
```

or:

```jsonnet
{ kind: 'AutoGridLayoutItem' }
```

it is a standalone value builder. Compose its nested mixins, then pass the result into the appropriate parent collection setter.

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

Examples of suspicious code that require correction or proof from the generated body:

```jsonnet
d.spec.withLayout(d.spec.layout.AutoGridLayoutKind.withKind() + ...)
qv.spec.withQuery(qv.spec.query.withKind() + ...)
d.spec.withTimeSettings(d.spec.timeSettings.withFrom('now-6h') + ...)
item.spec.withElement(item.spec.element.withKind() + ...)
```

## Validation

Before integrating a complicated builder chain, render the smallest possible fixture and inspect the shape.

For AutoGrid, require exactly:

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

for the relevant fragment after composition. There must be no extra `layout.spec.layout`, `layout.AutoGridLayoutKind`, `query.spec.query`, or other duplicate wrapper introduced by builder misuse.

The reviewer must `FAIL` source that double-wraps generated path mixins, even if Jsonnet renders successfully.