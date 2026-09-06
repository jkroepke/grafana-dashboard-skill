# Workflow artifacts and stage gates

Use files for every substantial handoff. Agent messages are control-plane signals only; never paste an artifact body into chat.

## Non-negotiable rules

- The coordinator writes only the run contract, dispatches stages, checks statuses/digests, and promotes the exact approved candidate.
- Each agent writes only its assigned artifact or candidate.
- An approval applies only to the exact SHA-256 digests it records.
- Any upstream change invalidates all downstream approvals.
- Only `promql-builder` may author or change query text that can enter the dashboard.
- Run every artifact through `scripts/validate_workflow_artifact.py` with all required `--input type=path` arguments.
- Run `scripts/verify_candidate_render.py` to prove the rendered JSON is the exact output of the candidate source.
- Run `scripts/verify_dashboard_contract.py` to prove the mandatory variable structure.
- Run `scripts/verify_query_parity.py` after rendering.
- Run `scripts/verify_non_prometheus_preservation.py` to reject any non-Prometheus consumer change.
- Run `scripts/verify_workflow_chain.py` before promotion.

This workflow version stages exactly one dashboard source file. If a task requires a shared-helper edit, return `BLOCKED` rather than editing or promoting multiple files without an atomic candidate-set contract.

## Run workspace and source staging

Create a neutral per-run scratch directory. Names MUST NOT contain application, customer, cluster, environment, endpoint, or dashboard identity.

Place the candidate Jsonnet beside the intended final source with a neutral hidden suffix such as `.candidate.jsonnet`, so relative imports behave identically. The builder MUST NOT write the final path.

The coordinator records the source baseline before dispatch. Promotion later fails if the final file no longer matches that baseline.

## Common envelope

Every JSON artifact has these fields:

```json
{
  "schema_version": 1,
  "artifact_type": "<type>",
  "run_id": "<neutral-id>",
  "revision": 1,
  "inputs": {"<upstream-type>": "sha256:<digest>"},
  "status": "DONE|PASS|FAIL|BLOCKED"
}
```

Schemas are closed: unknown fields fail validation. Input names and digests are stage-specific. The validator recomputes every supplied input digest and rejects missing, extra, or mismatched inputs. Direct dependencies use `--input`; transitive dependencies use `--support`. The validator recursively validates the entire supplied upstream graph, and rejects missing or extra support artifacts. A role receives support paths only for validation and MUST NOT read their bodies unless they are also direct role inputs.

`revision` is limited to `1..3`. A fourth correction artifact is invalid and must become a `BLOCKED` failure report for user direction.

For a successful metric shortlist use `DONE`. Every later successful gate uses `PASS`. A reviewer `FAIL` includes findings. If a stage cannot produce its normal artifact, write a `failure-report` with status `FAIL` or `BLOCKED`.

## Response contract

Return exactly one line, at most 256 characters:

```text
DONE <stage> artifact=<neutral-path> sha256=sha256:<64-lowercase-hex>
PASS <stage> artifact=<neutral-path> sha256=sha256:<64-lowercase-hex>
FAIL <stage> report=<neutral-path> sha256=sha256:<64-lowercase-hex>
BLOCKED <stage> report=<neutral-path> sha256=sha256:<64-lowercase-hex>
```

Do not include metrics, queries, findings, source, rendered JSON, API responses, or rejected alternatives in the response. When the client can save the raw specialist response to a neutral file, the coordinator runs `python3 scripts/validate_stage_response.py <response-file>` before accepting it; any grammar violation fails the stage.

## Run contract

The coordinator writes a `run-contract` artifact, at most 16 KiB, with `status: PASS`, `inputs: {}`, and:

```json
{
  "repository_root": "<absolute repository path>",
  "workspace": "<neutral scratch path>",
  "source": {
    "final_path": "<dashboard.jsonnet>",
    "candidate_path": "<adjacent .candidate.jsonnet>",
    "baseline_state": "ABSENT|PRESENT",
    "baseline_sha256": "sha256:<digest>|null"
  },
  "rendered_candidate_path": "<neutral scratch path>",
  "render": {
    "cwd": "<absolute repository path>",
    "argv": ["jsonnet", "-J", "vendor", "{source}"],
    "timeout_seconds": 120
  },
  "schema": {
    "dashboard": "V2|CLASSIC",
    "grafana_version": "<version>|null",
    "grafonnet_revision": "<revision>|null"
  },
  "limits": {
    "approved_metrics": 40,
    "changed_questions": 12,
    "changed_panels": 12,
    "changed_queries": 24,
    "total_panels": 48,
    "total_queries": 64,
    "findings": 20
  },
  "capabilities": {
    "datasource_access": true,
    "dashboard_api_validation": true,
    "publish_requested": false
  },
  "selector_proposals": {}
}
```

Run all workflow validators and gates with their working directory set to `repository_root`; the validator requires that field to equal its current working directory. This confines promotion to absolute `.jsonnet` paths inside the active repository. The candidate must be adjacent and named `<final-stem>.candidate.jsonnet`. `render.argv` is executed directly without a shell, contains exactly one standalone `{source}` argument, and must emit the rendered dashboard JSON on stdout. Candidate source containing `std.thisFile` is rejected because renaming it could change the final render.

Limits may be lowered per run but never raised above these hard ceilings. `changed_*` limits count `NEW` and `MODIFIED` records; preserved existing records count only against `total_*`. If an existing dashboard exceeds a hard total ceiling, stop and ask the user to split or explicitly redesign the workflow rather than dropping queries from attestation.

`selector_proposals` are unapproved evidence. Only selectors in the later metrics contract are authoritative downstream.

Validate:

```bash
python3 scripts/validate_workflow_artifact.py <run-contract.json>
```

## Metric shortlists

`application-metrics` and `kubernetes-metrics` each write at most 64 KiB and 48 records in `metrics`. They may reference a complete NDJSON catalog using `catalog_ref`. Retrieve catalog records selectively; do not load the full catalog into an agent context.

Each metric record has exactly:

```json
{
  "id": "M001",
  "source": "APPLICATION|PROCESS|KSM|KUBELET|SCRAPE|SCHEDULER|RECORDING_RULE",
  "category": "BUSINESS|PROCESS|KUBERNETES",
  "family": "<metric family>",
  "members": ["<family member>"],
  "type": "counter|gauge|histogram|summary|info|stateset|unknown",
  "unit": "<unit>|null",
  "help": "<observed help text>|null",
  "observed_labels": ["<label name>"],
  "stored_labels": ["<verified label name>"],
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

Required input: `run-contract`.

## Approved metrics contract

`metrics-reviewer` writes `metrics-contract`, at most 64 KiB, with:

- `approved`: at most the run limit; unique reviewed metric records
- `rejected`: bounded IDs/reason codes for reviewed-but-rejected records
- `not_considered`: remaining shortlist IDs so they cannot be rediscovered silently
- `selector_contract`: approved application/Kubernetes labels, populations, and fixed-selector references
- `unresolved`: concise evidence gaps

Each approved record has exactly:

```json
{
  "id": "AM001",
  "source_artifact": "application-metrics|kubernetes-metrics",
  "source_metric_id": "M001",
  "source": "APPLICATION|PROCESS|KSM|KUBELET|SCRAPE|SCHEDULER|RECORDING_RULE",
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

`selector_contract` has exactly `application_namespace_label`, `application_pod_label`, `kubernetes_namespace_label`, `kubernetes_pod_label`, `cluster_label`, `fixed_selector_refs`, `population_notes`, and `scrape_interval_ref`. Nullable labels remain null when unavailable; references point to neutral evidence rather than embedding target-specific selector values in prompts.

Approved identity/dimension labels and selector labels must already occur in the corresponding shortlist evidence. The reviewer cannot introduce a new label name; it routes missing evidence back to the owning analyst.

`PRESERVE_ONLY` is allowed only for an unchanged legacy dependency whose uncertainty is explicit. It cannot support a new or modified question/query. A blocking legacy conflict requires user direction; it is not silently dropped or rewritten.

Required inputs: `run-contract` and at least one metric shortlist.

## Dashboard plan

`dashboard-architect` writes `dashboard-plan`, at most 64 KiB, containing exact arrays:

- `panel_groups`: `{id, title, placement, order}`
- `questions`: `{id, text, priority, category, metric_ids, calculation, result_shape, retained_labels, no_data_requirement, change}`
- `panels`: `{id, question_ids, group_id, visualization, placement, size, change}`
- `required_consumers`: variable/annotation items `{id, role, rendered_name, purpose, metric_ids}`
- `omissions`: `{id, reason}`
- `budgets`: an exact copy of the run limits used

`change` is `NEW`, `MODIFIED`, or `PRESERVED`. New/modified and total records obey separate run limits. The plan contains no query text, selector expression, plugin payload, Jsonnet, or rendered JSON.

Every question must be assigned to at least one panel. Orphaned questions are invalid.

The rendered candidate's complete panel-ID set must exactly equal the plan's panel-ID set, including preserved or queryless panels. This makes total/change panel budgets enforceable and prevents hidden panels.

With an absent source baseline, every question and panel must be `NEW`. For updates, the full-chain gate independently renders the baseline and candidate: panel JSON determines panel change status, and the linked panel statuses determine question change status. Incorrect labels fail before promotion.

Required inputs: `run-contract`, `metrics-contract`.

## Query pack

`promql-builder` writes `query-pack`, at most 128 KiB. It is the only artifact that may contain final Prometheus query text. `queries` contains at most the run's total-query limit; new/modified queries obey `changed_queries`.

Every Prometheus query that will exist in the final dashboard—including preserved legacy panel, variable, and annotation queries—has exactly:

```json
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

For a Prometheus variable query, `plugin_query_model` is instead exactly:

```json
{
  "qry_type": 1,
  "editor_ref_id": "PrometheusVariableQueryEditor-VariableQuery"
}
```

`qry_type` is required for V2 and may be null for classic dashboards when the classic model has no equivalent. `editor_ref_id` must equal the consumer locator `ref_id`. Panel and annotation records use null. Explicitly non-Prometheus consumers are outside this pack and must remain exactly unchanged; adding, changing, or removing one is out of scope and returns `BLOCKED`.

Expressions are non-empty and at most 4096 characters. Panel locators use the planned panel ID as their V2 element key. Variable and annotation locators use the corresponding `rendered_name` from `required_consumers`. For preserved classic panels use `panel-<numeric-id>` as the locator name. Panel queries map to planned panels/questions. Variable and annotation queries map to `required_consumers`. `PRESERVED` queries may use only `PRESERVE_ONLY` or `PLAN` metrics; new/modified queries require `PLAN` metrics.

Every planned panel, operational question, and required Prometheus variable/annotation consumer must be covered by the query pack. With an absent baseline every query must be `NEW`. For updates, the full-chain gate compares exact locator/text/mode/datasource/query-model tuples with the independently rendered baseline and rejects false change labels or removed Prometheus consumers. `datasource_ref` must be exactly `${datasource}` for every record; literal datasource UIDs are invalid.

Required inputs: `run-contract`, `metrics-contract`, `dashboard-plan`.

## PromQL review

`promql-reviewer` writes `query-review`, at most 32 KiB, with:

```json
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

`dashboard-builder` writes the candidate, rendered JSON, and a `dashboard-build` artifact at most 32 KiB:

```json
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

`PASS` requires every query-pack ID exactly once, no omissions, all mandatory checks `PASS`, and candidate/rendered/baseline values equal to the run contract and current files.

Run:

```bash
python3 scripts/verify_candidate_render.py \
  <run-contract.json> <dashboard-build.json>
python3 scripts/verify_dashboard_contract.py \
  <rendered-dashboard.json>
python3 scripts/verify_query_parity.py \
  <query-pack.json> <query-review.json> <rendered-dashboard.json>
python3 scripts/verify_non_prometheus_preservation.py \
  <rendered-dashboard.json> [--baseline <baseline-render.json>]
```

Required inputs: `run-contract`, `metrics-contract`, `dashboard-plan`, `query-pack`, `query-review`.

## Dashboard review

`dashboard-reviewer` writes `dashboard-review`, at most 32 KiB, with:

```json
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

When a normal artifact cannot be produced, write `failure-report`, at most 16 KiB, containing only:

```json
{
  "failed_stage": "<agent id>",
  "owner": "<agent id or USER>",
  "code": "<stable code>",
  "summary": "<concise sanitized blocker>",
  "evidence_refs": ["<up to three neutral references>"]
}
```

Use status `FAIL` or `BLOCKED`. It requires at least the run-contract input; add other already-valid upstream digests when relevant.

## Validation commands

Example with required upstream digest checks:

```bash
python3 scripts/validate_workflow_artifact.py query-pack.json \
  --input run-contract=run-contract.json \
  --input metrics-contract=metrics-contract.json \
  --input dashboard-plan=dashboard-plan.json \
  --support application-metrics=application-metrics.json
```

Also supply `--support kubernetes-metrics=kubernetes-metrics.json` when that shortlist is in the metrics-contract input graph. Later stages additionally supply any earlier artifacts that are transitive rather than direct. The validator output supplies the artifact digest for the bounded response. Do not copy any artifact body into the coordinator context.

## Chain and promotion gate

Limit query build/review and dashboard build/review correction loops to three revisions. On a third failure, return `BLOCKED` rather than continuing.

Before promotion, run the read-only full-chain check:

```bash
python3 scripts/verify_workflow_chain.py \
  run-contract.json metrics-contract.json dashboard-plan.json query-pack.json \
  query-review.json dashboard-build.json dashboard-review.json \
  --application-metrics application-metrics.json \
  --kubernetes-metrics kubernetes-metrics.json
```

Supply only the metric shortlist paths that exist. The gate recomputes every digest, checks the DAG/status invariants, checks query parity, and verifies the final source baseline and exact reviewed candidate.

Only after that command returns `PASS`, promote the candidate with the same command plus `--promote`. It repeats all checks, refuses to overwrite a changed destination, and verifies the final-path render before returning `PASS`. Publication is separate and requires explicit user intent.

The chain re-renders both baseline and candidate with the shell-free run-contract command, requires the complete rendered panel set to equal the bounded plan, checks objective `NEW`/`MODIFIED`/`PRESERVED` classification, validates mandatory variables, compares every approved Prometheus consumer, and requires the complete explicitly non-Prometheus consumer fingerprint to remain unchanged. Promotion uses atomic no-clobber creation for an absent destination or an atomic exchange for an existing destination; a baseline or final-render mismatch rolls the exchange back.

## Publication report

When `publish_requested` is true, a fresh `dashboard-publisher` handles the external write after promotion and writes `publish-report`, at most 16 KiB, with:

```json
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

Required inputs: `run-contract`, `dashboard-build`, `dashboard-review`. The validator requires explicit publication intent, the exact reviewed source at the final repository path, and successful target readback. Publication failures use `failure-report`; the coordinator never constructs or repairs API payloads.

After promotion, recursive build validation accepts the reviewed source digest at the final path when the candidate path is absent. The publisher verifies that path explicitly with `verify_candidate_render.py ... --source <final-source.jsonnet>` before any target write.
