# Workflow artifacts and stage gates

Use files for every substantial handoff. Agent messages are control-plane
signals only; never paste an artifact body into chat. Read
`knowledge/workflow/workspace.md` first and use its small-record checkpoint
protocol throughout every stage.

## Non-negotiable rules

- The coordinator writes only the run contract, dispatches stages, checks statuses/digests, and promotes the exact approved candidate.
- Each agent writes only inside its assigned agent/run workspace, plus the
  dashboard candidate when owned by `dashboard-builder`.
- An approval applies only to the exact SHA-256 digests it records.
- Any upstream change invalidates all downstream approvals.
- Only `promql-builder` may author or change query text that can enter the dashboard.
- Use `./workflow stage-check` to validate the assigned artifact and produce the stage response.
- A `stage-check` response is terminal: immediately return that exact line and run no further command, inspection, or explanation.
- Dashboard build, review, and publication stages use `./workflow dashboard-integrity` before their terminal action. It derives fixed paths and runs the required mechanical checks from the ticket.
- The coordinator runs `./workflow chain-check` before `./workflow promote`.
- The run contract must record Dashboard Schema V2 and a Grafana version of v13 or later. This workflow rejects classic dashboard sources and does not perform migrations.

This workflow version stages exactly one dashboard source file. If a task requires a shared-helper edit, return `BLOCKED` rather than editing or promoting multiple files without an atomic candidate-set contract.

## Run workspace and source staging

The coordinator creates `dashboards/<project-name>/workspace`. Each role uses
`<workspace>/<agent>/<run-id>/` with the required `inbox/`, `records/`,
`evidence/`, `outbox/`, `tmp/`, and `state.yaml` structure. The run ID and all
names below the project workspace MUST NOT contain customer, cluster,
environment, endpoint, dashboard-resource identity, or credentials.

Agents may use Mike Farah `yq` v4 for one small decision checkpoint during
work. Role-local deterministic assemblers own every normal stage artifact:
they collect fixed records, derive envelopes/digests/status fields, and write
the draft. Agents must not use `yq` to assemble arrays, project objects, load
multiple files, or construct a final artifact. Workflow artifacts with `.json`
or `.yml` filenames are invalid.
Rendered dashboards remain JSON.

Place the candidate Jsonnet beside the intended final source with a neutral hidden suffix such as `.candidate.jsonnet`, so relative imports behave identically. The builder MUST NOT write the final path.

The coordinator records the source baseline before dispatch. Promotion later fails if the final file no longer matches that baseline.

## Common envelope

Every YAML artifact has these fields. Schema examples use flow-style YAML to
show types without ambiguity:

```yaml
{
  "schema_version": 1,
  "artifact_type": "<type>",
  "run_id": "<neutral-id>",
  "revision": 1,
  "inputs": {"<upstream-type>": "sha256:<digest>"},
  "status": "DONE|PASS|FAIL|BLOCKED"
}
```

Schemas are closed: unknown fields fail validation. Input names and digests are stage-specific. The workflow validator recomputes every supplied input digest and rejects missing, extra, or mismatched inputs. Direct dependencies use `--input`; transitive dependencies use `--support`. It recursively validates the entire supplied upstream graph and rejects missing or extra support artifacts. A role receives support paths only for validation and MUST NOT read their bodies unless they are also direct role inputs.

Every `evidence_ref` and `evidence_refs` entry is a local file reference, with
an optional `:line` or `#fragment` locator. Relative references resolve from the
agent run directory when the artifact is in `outbox/`, otherwise from the
artifact directory. The referenced file must exist as a regular, non-symlink
file inside the repository; labels such as `runtime-capabilities` without a
corresponding file are invalid.

`revision` is limited to `1..3`. A fourth correction artifact is invalid and must become a `BLOCKED` failure report for user direction.

For a successful metric shortlist use `DONE`. Every later successful gate uses `PASS`. A reviewer `FAIL` includes findings. If a stage cannot produce its normal artifact, write a `failure-report` with status `FAIL` or `BLOCKED`.

## Response contract

Return exactly one line, at most 256 characters:

```text
DONE <stage> artifact=<neutral-path>.yaml sha256=sha256:<64-lowercase-hex>
PASS <stage> artifact=<neutral-path>.yaml sha256=sha256:<64-lowercase-hex>
FAIL <stage> report=<neutral-path>.yaml sha256=sha256:<64-lowercase-hex>
BLOCKED <stage> report=<neutral-path>.yaml sha256=sha256:<64-lowercase-hex>
```

The referenced workflow file MUST have the exact `.yaml` suffix. Do not include
metrics, queries, findings, source, rendered JSON, API responses, or rejected
alternatives in the response. `./workflow stage-check` produces the response;
the coordinator accepts it through its fixed control operation. Its output is
terminal: do not list files, query YAML, inspect evidence, or otherwise verify
the artifact after it prints the line.

## Run contract

The coordinator creates and validates the immutable run contract before any
specialist dispatch. It carries the fixed source, rendering, compatibility,
limit, and capability bindings for the run. Specialists receive only its
ticketed binding; they do not create, edit, or inspect run-contract internals.

Run limits are enforced by dispatch and validators. The metrics contract, not
the run contract, is the authoritative selector/population contract.

## Metric shortlists

`application-metrics` and `kubernetes-metrics` each write at most 64 KiB and 48
records in `metrics`. Every shortlist includes:

```yaml
catalog_ref: <local catalog/index reference or null>
metrics: [<metric records>]
omission_counts: {<omission-code>: <non-negative count>}
```

Use `omission_counts: {}` when no families were omitted. `application-metrics` runs first and additionally writes
one immutable local scope evidence file containing the exact non-empty namespace
set represented by verified application stored series. Its file content is a
bare JSON array of strings, not an object wrapper. Its artifact includes:

```yaml
namespace_scope:
  evidence_ref: <absolute local scope-evidence path>
  sha256: sha256:<digest of that exact file>
  namespace_count: <positive integer>
```

The namespace values themselves are never included in an artifact. The
`kubernetes-metrics` artifact requires `application-metrics` as a direct input
and repeats the exact `namespace_scope_ref` and `namespace_scope_sha256`; the
The workflow validator requires both to match the application artifact. The Kubernetes agent
uses that set, including every member when it contains multiple namespaces, for
every discovery request. During discovery analysts write one YAML file per
metric family under `records/metrics/`; `stage-finish` creates
the bounded shortlist. `catalog_ref` may reference an index for
additional small YAML records. Retrieve records selectively; do not load the
full catalog into an agent context.

```yaml
# kubernetes-metrics.yaml
inputs:
  run-contract: sha256:<digest>
  application-metrics: sha256:<digest>
namespace_scope_ref: <the exact application namespace_scope.evidence_ref>
namespace_scope_sha256: sha256:<the exact application namespace_scope.sha256>
```

Each metric record has these required fields (plus optional `documented_labels`):

```yaml
{
  "id": "M00001",
  "source": "APPLICATION|PROCESS|KSM|KUBELET|SCRAPE|SCHEDULER|ISTIO|RECORDING_RULE",
  "category": "BUSINESS|PROCESS|KUBERNETES",
  "family": "<metric family>",
  "members": ["<family member>"],
  "type": "counter|gauge|histogram|summary|info|stateset|unknown",
  "unit": "<unit>|null",
  "help": "<observed help text>|null",
  "observed_labels": ["<label name>"],
  "stored_labels": ["<verified label name>"],
  "documented_labels": ["<catalog label name>"],
  "match_keys": ["<label name>"],
  "population": "<observed population>|unknown",
  "lifecycle": "<observed fact>|unknown",
  "availability": "OBSERVED|LIVE_VERIFIED|DOCUMENTED|UNVERIFIED",
  "cardinality_risk": "LOW|MEDIUM|HIGH|UNKNOWN",
  "evidence_refs": ["<neutral reference>"],
  "limitations": ["<fact or uncertainty>"]
}
```

Analysts record facts only. These artifacts contain no operational questions, dashboard priorities, query text, or source fragments.

`documented_labels` is optional and is used only by a fixed local preset
catalogue. It records a documentation claim, not target observation. A reviewer
must independently verify every documented family and label before approving it
for `PLAN`.

Required input: `run-contract`.

## Approved metrics contract

`metrics-reviewer` writes `metrics-contract.yaml`, at most 64 KiB, assembling
its approved, rejected, and not-considered entries from separate YAML records:

- `approved`: at most the run limit; unique reviewed metric records
- `rejected`: bounded IDs/reason codes for reviewed-but-rejected records
- `not_considered`: remaining shortlist IDs so they cannot be rediscovered silently
- `selector_contract`: approved application/Kubernetes labels, populations, and fixed-selector references
- `unresolved`: a list of concise evidence-gap strings; use `[]` when none

`dashboard-architect` runs `./dashboard-capabilities` after ticket validation.
It emits `evidence/approved-capabilities.json`, the bounded planning projection
of the ticketed approved metrics contract. Do not build an equivalent `yq`
projection in an agent command.

The payload has this fixed top-level shape:

```yaml
approved: [<reviewed metric records>]
rejected:
  - source_artifact: application-metrics|kubernetes-metrics
    metric_id: <source metric ID>
    reason_code: <stable reason code>
    reason: <evidence-backed reason>
not_considered:
  - source_artifact: application-metrics|kubernetes-metrics
    metric_id: <source metric ID>
selector_contract: <selector contract object>
unresolved: [<evidence-gap string>]
```

Each approved record has exactly:

```yaml
{
  "id": "AM001",
  "source_artifact": "application-metrics|kubernetes-metrics",
  "source_metric_id": "M00001",
  "source": "APPLICATION|PROCESS|KSM|KUBELET|SCRAPE|SCHEDULER|ISTIO|RECORDING_RULE",
  "category": "BUSINESS|PROCESS|KUBERNETES",
  "family": "<metric family>",
  "type": "<verified type>",
  "unit": "<unit>|null",
  "semantics": "<reviewed meaning>",
  "lifecycle": "<reviewed lifecycle>",
  "label_layer": "APPLICATION_STORED|KUBERNETES_NATIVE",
  "identity_labels": ["<label name>"],
  "bounded_dimensions": ["<label name>"],
  "availability": "VERIFIED|UNVERIFIED",
  "allowed_use": "PLAN|PRESERVE_ONLY",
  "risks": ["<risk>"],
  "evidence_refs": ["<neutral reference>"]
}
```

`selector_contract` has exactly `application_namespace_label`, `application_pod_label`, `kubernetes_namespace_label`, `kubernetes_pod_label`, `istio_source_namespace_label`, `istio_destination_namespace_label`, `cluster_label`, `fixed_selector_refs`, `population_notes`, and `scrape_interval_ref`. Nullable labels remain null when unavailable; references point to neutral evidence rather than embedding target-specific selector values in prompts.

`population_notes` is always an array of at most eight strings, including when
there is one note: `population_notes: ["regular application containers"]`.
When datasource access is enabled, routine Kubernetes evidence references are
created only by `./metrics-review-probes`; use its stable response path
`evidence/metrics-review-probes/responses/<metric-id>.json`, never a manually
chosen `evidence/probes/...` path.

For `rejected` and `not_considered`, use `./metric-disposition` from the
metrics-reviewer workspace. It checks each source/metric ID against the exact
ticketed shortlist and creates one immutable checkpoint per ID; do not derive
IDs with shell arithmetic or `printf`.

`source`, `category`, `family`, and `type` are copied unchanged from the
shortlist record. The reviewer cannot correct a source record: when its facts
or classification conflict with evidence, reject it with an evidence-backed
reason and route it to the owning analyst for revision. Approved
identity/dimension labels and selector labels must already occur in the
corresponding shortlist evidence. The reviewer cannot introduce a new label
name; it routes missing evidence back to the owning analyst.

`PRESERVE_ONLY` is allowed only for an unchanged legacy dependency whose uncertainty is explicit. It cannot support a new or modified question/query. A blocking legacy conflict requires user direction; it is not silently dropped or rewritten.

Required inputs: `run-contract` and at least one metric shortlist.

## Dashboard plan

`stage-finish` writes `dashboard-plan.yaml`, at most 64 KiB, from
fixed question, panel, consumer, and omission checkpoint directories:

- `panel_groups`: `{id, title, placement, order}`
- `questions`: `{id, text, priority, category, metric_ids, calculation, result_shape, retained_labels, row_identity_labels, no_data_requirement, change}`
- `panels`: `{id, question_ids, group_id, visualization, placement, size, change}`
- `required_consumers`: variable/annotation items `{id, role, rendered_name, purpose, metric_ids}`
- `omissions`: `{id, reason}`
- `budgets`: an exact copy of the run limits used

`required_consumers` contains only actual Prometheus `QueryVariable` and
annotation queries. The mandatory `datasource` `DatasourceVariable` is a
queryless builder-owned control, so it must not appear in this array or in the
query pack.

Question `priority` is exactly `MUST` or `SHOULD`; `category` is exactly
`BUSINESS`, `PROCESS`, or `KUBERNETES`; and `result_shape` is exactly
`SCALAR`, `TIME_SERIES`, `LABEL_SET`, or `DISTRIBUTION`. These are closed
enums, not free-form severity labels.

`LABEL_SET` questions require a non-empty `row_identity_labels` tuple, formed
only from approved metric labels. Other result shapes set it to `[]`. Panel
query `result_identity` must exactly equal the planned tuple; live probes test
that the returned tuple is unique.

`change` is `NEW`, `MODIFIED`, or `PRESERVED`. New/modified and total records obey separate run limits. The plan contains no query text, selector expression, plugin payload, Jsonnet, or rendered JSON.

For an update, `changed_questions`, `changed_panels`, and `changed_queries`
limit the new/modified work. For a new dashboard, every record is `NEW`, so
the corresponding total capacities (`total_panels` and `total_queries`) apply
instead. This prevents an update-safety budget from suppressing valid
greenfield operational questions.

Every question must be assigned to at least one panel. Orphaned questions are invalid.

The rendered candidate's complete panel-ID set must exactly equal the plan's panel-ID set, including preserved or queryless panels. This makes total/change panel budgets enforceable and prevents hidden panels.

With an absent source baseline, every question and panel must be `NEW`. For updates, the full-chain gate independently renders the baseline and candidate: panel JSON determines panel change status, and the linked panel statuses determine question change status. Incorrect labels fail before promotion.

Required inputs: `run-contract`, `metrics-contract`.

## Query pack

`promql-builder` writes one YAML record per query immediately after authoring
and validation; `stage-finish` creates `query-pack.yaml`, at most 128
KiB. It is the only artifact that may contain final Prometheus query
text. `queries` contains at most the run's total-query limit; new/modified
queries obey `changed_queries`.

Every Prometheus query that will exist in the final dashboard—including preserved legacy panel, variable, and annotation queries—has exactly:

```yaml
{
  "id": "T001",
  "role": "PANEL|VARIABLE|ANNOTATION",
  "consumer_id": "<planned panel/consumer id>",
  "consumer_locator": {
    "kind": "PANEL|VARIABLE|ANNOTATION",
    "name": "<rendered element key, variable name, or annotation name>",
    "ref_id": "A|null"
  },
  "plugin_query_model": null,
  "question_id": "Q001|null",
  "metric_ids": ["AM001"],
  "language": "PROMQL|PROMETHEUS_VARIABLE",
  "expression": "<exact dashboard-ready text>",
  "mode": "INSTANT|RANGE|VARIABLE",
  "datasource_ref": "${datasource}",
  "unit": "<unit>|null",
  "result_identity": ["<label name>"],
  "no_data_semantics": "<meaning>",
  "expected_cardinality": "<bounded expectation>",
  "assumptions": ["<assumption>"],
  "edge_cases": ["<edge case>"],
  "change": "NEW|MODIFIED|PRESERVED",
  "validation": {
    "static": "PASS",
    "live": "PASS|UNVERIFIED",
    "evidence_refs": ["<neutral reference>"]
  }
}
```

The workflow validator rejects `rate()`, `irate()`, `increase()`, or `resets()`
when the referenced approved metric is a gauge, info, stateset, or unknown type.
This is checked from approved metadata and expression structure; a `_total`
suffix never upgrades a gauge to a counter.

For a Prometheus variable query, `plugin_query_model` is instead exactly:

```yaml
{
  "qry_type": 1,
  "editor_ref_id": "PrometheusVariableQueryEditor-VariableQuery"
}
```

`qry_type` is required. `editor_ref_id` must equal the consumer locator `ref_id`. Panel and annotation records use null. Explicitly non-Prometheus consumers are outside this pack and must remain exactly unchanged; adding, changing, or removing one is out of scope and returns `BLOCKED`.

Expressions are non-empty and at most 4096 characters. Panel locators use the planned panel ID as their V2 element key. Variable and annotation locators use the corresponding `rendered_name` from `required_consumers`. Panel queries map to planned panels/questions. Variable and annotation queries map to `required_consumers`. `PRESERVED` queries may use only `PRESERVE_ONLY` or `PLAN` metrics; new/modified queries require `PLAN` metrics.

Every planned panel, operational question, and required Prometheus variable/annotation consumer must be covered by the query pack. With an absent baseline every query must be `NEW`. For updates, the full-chain gate compares exact locator/text/mode/datasource/query-model tuples with the independently rendered baseline and rejects false change labels or removed Prometheus consumers. `datasource_ref` must be exactly `${datasource}` for every record; literal datasource UIDs are invalid.

Required inputs: `run-contract`, `metrics-contract`, `dashboard-plan`.

## PromQL review

`promql-reviewer` writes `query-review.yaml`, at most 32 KiB, assembling any
findings from one small YAML record per reviewed query:

```yaml
{
  "query_pack_sha256": "sha256:<digest>",
  "query_count": 1,
  "live_validation": "PASS|UNVERIFIED|FAIL",
  "findings": [
    {
      "query_id": "T001",
      "code": "<stable code>",
      "evidence_ref": "<neutral reference>|null",
      "required_change": "<semantic requirement without replacement query>"
    }
  ]
}
```

`PASS` requires zero findings, matching pack digest/count, and no failed live validation. The reviewer never supplies corrected query text.

Validate panel and annotation expressions through Prometheus instant/range APIs. Validate variable-query records through the pinned Grafana Prometheus variable-query model or equivalent metadata operations; `label_values(...)` is not standalone PromQL.

Required inputs: `run-contract`, `metrics-contract`, `dashboard-plan`, `query-pack`.

## Dashboard build

`dashboard-builder` writes the candidate and rendered JSON;
`stage-finish` creates its `dashboard-build.yaml` artifact at most
32 KiB from current files and exactly one
`records/local-schema/*.yaml` checkpoint containing `{status: PASS|UNVERIFIED}`:

```yaml
{
  "candidate_path": "<path>",
  "candidate_sha256": "sha256:<digest>",
  "rendered_path": "<path>",
  "rendered_sha256": "sha256:<digest>",
  "query_pack_sha256": "sha256:<digest>",
  "query_review_sha256": "sha256:<digest>",
  "baseline_state": "ABSENT|PRESENT",
  "baseline_sha256": "sha256:<digest>|null",
  "integrated_query_ids": ["T001"],
  "checks": {
    "format": "PASS",
    "render": "PASS",
    "json": "PASS",
    "query_parity": "PASS",
    "local_schema": "PASS|UNVERIFIED",
    "layout_references": "PASS",
    "variable_payloads": "PASS"
  },
  "findings": []
}
```

`PASS` requires every query-pack ID exactly once, no omissions, all mandatory checks `PASS`, and candidate/rendered/baseline values equal to the current ticketed files. Run `./workflow dashboard-integrity` before writing it.

Required inputs: `run-contract`, `metrics-contract`, `dashboard-plan`, `query-pack`, `query-review`.

## Dashboard review

`stage-finish` writes `dashboard-review.yaml`, at most 32 KiB,
from fixed checkpointed checks/findings:

```yaml
{
  "build_manifest_sha256": "sha256:<digest>",
  "candidate_sha256": "sha256:<digest>",
  "rendered_sha256": "sha256:<digest>",
  "query_pack_sha256": "sha256:<digest>",
  "query_review_sha256": "sha256:<digest>",
  "query_parity": "PASS|FAIL",
  "target_dry_run": "PASS|NOT_CONFIGURED|FAIL",
  "findings": [
    {
      "owner": "DASHBOARD_BUILD|QUERY_PACK_CHANGE_REQUIRED|METRICS_OR_PLAN_CHANGE_REQUIRED",
      "code": "<stable code>",
      "artifact_ref": "<neutral reference>",
      "evidence_ref": "<neutral reference>|null",
      "required_change": "<requirement without source or query replacement>"
    }
  ]
}
```

`PASS` requires zero findings, query parity `PASS`, exact current digests, and target dry-run `PASS` when the run contract says validation access exists. Otherwise dry-run is `NOT_CONFIGURED`.

Required inputs: `run-contract`, `dashboard-plan`, `query-pack`, `query-review`, `dashboard-build`.

## Failure report

When a normal artifact cannot be produced, first write one or more
evidence files below the relevant agent workspace, then run local
`./stage-failure-report --finish`. It validates and promotes the ticket-bound
draft, finalizes state, and emits the terminal line.
The coordinator uses its fixed
`failure-report` action only for a coordinator-owned blocker.

A failure report is at most 16 KiB and contains only:

```yaml
{
  "failed_stage": "<agent id>",
  "owner": "<agent id or USER>",
  "code": "<stable code>",
  "summary": "<concise blocker>",
  "evidence_refs": ["<up to three neutral references>"]
}
```

Use status `FAIL` or `BLOCKED`. It requires the run-contract input.

## Chain and promotion gate

Limit query build/review and dashboard build/review correction loops to three revisions. On a third failure, return `BLOCKED` rather than continuing.

Before promotion, run the read-only full-chain check:

```bash
./workflow chain-check
```

The gate derives the canonical artifacts for the active workspace run, recomputes every digest, checks the DAG/status invariants, checks query parity, and verifies the final source baseline and exact reviewed candidate.

Only after that command returns `PASS`, the coordinator runs its fixed promote
operation. It repeats all checks, refuses to overwrite a changed destination,
and verifies the final-path render before returning `PASS`. Publication is
separate and requires explicit user intent.

The chain re-renders both baseline and candidate with the shell-free run-contract command, requires the complete rendered panel set to equal the bounded plan, checks objective `NEW`/`MODIFIED`/`PRESERVED` classification, validates mandatory variables, compares every approved Prometheus consumer, and requires the complete explicitly non-Prometheus consumer fingerprint to remain unchanged. Promotion uses atomic no-clobber creation for an absent destination or an atomic exchange for an existing destination; a baseline or final-render mismatch rolls the exchange back.

## Publication report

When `publish_requested` is true, a fresh `dashboard-publisher` handles the
external write after promotion and writes `publish-report.yaml`, at most 16 KiB,
from its checkpointed request/readback results:

```yaml
{
  "dashboard_review_sha256": "sha256:<digest>",
  "promoted_source_sha256": "sha256:<digest>",
  "rendered_sha256": "sha256:<digest>",
  "operation": "CREATE|UPDATE",
  "write_status": "PASS",
  "readback_status": "PASS",
  "evidence_refs": ["<neutral reference>"]
}
```

Required inputs: `run-contract`, `dashboard-build`, `dashboard-review`. The workflow validator requires explicit publication intent, the exact reviewed source at the final repository path, and successful target readback. Publication failures use `failure-report`; the coordinator never constructs or repairs API payloads.

Before the target write, the publisher runs the checked dashboard-integrity helper to verify the promoted final source.
