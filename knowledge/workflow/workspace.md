# Filesystem workspace and YAML queue

Use the repository filesystem as durable working memory. Agent context is a
cache, not the system of record.

## Required layout

The coordinator selects filesystem-safe `<project-name>` and `<run-id>` values.
Every role works below its own directory:

```text
dashboards/<project-name>/workspace/<agent>/<run-id>/
├── inbox/       immutable job tickets from the coordinator
├── records/     small structured findings, one logical item per YAML file
│   └── done/    completed metric-family work items; never reprocess these
├── evidence/    raw evidence kept out of YAML records
├── outbox/      completed stage artifact or failure report
├── tmp/         incomplete files; never hand these to another stage
└── state.yaml   small resumable progress snapshot
```

The shared access configuration is never included in artifacts and workflow
wrappers load it automatically from this workspace or a descendant role
directory.

The coordinator's dispatch operation initializes this directory. Specialists
receive its path in their ticket and do not initialize it themselves.

`scripts/stage_check.py` validates the checkpoint area and assigned artifact
before a specialist returns its response.

`scripts/validate_agent_workspace.sh` rejects missing layout/state, inbox/record symlinks, non-YAML
structured files, invalid/non-mapping YAML, inbox/record files over 8 KiB, and
state over 16 KiB. When an outbox contains a terminal stage artifact,
`scripts/validate_agent_workspace.sh` also requires `state.status` to equal the artifact status and
`state.next_action` to be `complete`, `pending` to be empty, and `completed` to
contain the terminal artifact path. A coordinator run contract alone is not a
terminal artifact.

The coordinator runs its `dispatch` operation before each stage. It writes one
immutable, at-most-8-KiB `inbox/job.yaml`, validates
all bindings, and updates coordinator state. The ticket contains the
run/stage/revision, approved input paths and digests, assigned output paths,
budgets, and opaque capability references—never artifact bodies or raw
evidence. The dispatch prompt contains only the agent ID, absolute project workspace path,
and ticket path. The specialist runs `scripts/coordinator_stage.py validate-ticket` before work;
the coordinator uses `accept` on its bounded response.

## Coordinator control paths

Coordinator control operations run from `dashboards/<project-name>/workspace/`.
`set-workflow-env` accepts exactly one name/value pair per invocation:
`set-workflow-env <name> <value>`. Do not pass multiple pairs in one call.

After `run-contract`, invoke a specialist with:

```text
dispatch --run-contract coordinator/<run-id>/outbox/run-contract.yaml --agent <agent-id>
```

The run-contract path is relative to this `workspace/` directory (or absolute).
Do not pass `dashboards/<project-name>/workspace/...` as a relative path: the
controller resolves it from `workspace/`, which duplicates that prefix.
`dispatch` creates the ticket and returns its path; workspace and ticket paths
are inputs to the specialist handoff, not to `dispatch`.

A job ticket uses this bounded shape; unused maps/lists stay empty rather than
growing the dispatch prompt:

```yaml
schema_version: 1
workspace: /absolute/path/to/dashboards/project/workspace
run_id: run-001
agent: application-metrics
revision: 1
inputs:
  run-contract:
    path: coordinator/run-001/outbox/run-contract.yaml
    sha256: sha256:<digest>
supports: {}
evidence_refs:
  - evidence/source-index.yaml
namespace_scope: null
outputs:
  artifact: outbox/application-metrics.yaml
  failure_report: outbox/failure-report.yaml
  candidate: null
  rendered: null
limits: {}
capability_refs: []
```

Relative paths are resolved from the project `workspace/` root; paths may be
absolute when required by an artifact contract. Every digest is computed from
the exact referenced bytes. The specialist validates the ticket and all
declared digests before processing its first queue item.

## Deterministic execution paths

Use deterministic tools for routine mechanics; do not spend model context
recreating their output.

- `metrics-sync` fetches/snapshots application exposition and resumes its
  queue. `scripts/metric_facts.py` copies bounded observed facts and marks every
  family `NEEDS_AI`; it never guesses operational semantics.
- `scripts/promql_templates.py <request.json> <result.json>` compiles only an
  allowlisted typed template. Unknown templates and joins are `CUSTOM` work.
- `scripts/prometheus_probe_matrix.py` defaults to `inbox/job.yaml`, runs a
  declared matrix, stores raw responses in `evidence/`, and checks response
  status, warnings, cardinality, labels, and duplicate identities.
- `scripts/grafana_dry_run.py ... --operation UPDATE` performs the required
  GET and metadata-preserving dry-run PUT. `scripts/grafana_publish.py`
  defaults to `inbox/job.yaml` and performs the equivalent real transaction
  only after ticket/integrity/review preflight passes.

These scripts are closed-input exception boundaries. The model remains
responsible for dashboard intent, ambiguous metric meaning, and `CUSTOM`
PromQL—not a free-form PASS assertion.

After dispatch, only the assigned specialist writes in `records/`, `evidence/`,
`tmp/`, `outbox/`, and its `state.yaml`. No two agents write the same file.
Downstream stages read approved `outbox/` artifacts and selected record files;
they never edit them.

After a specialist cancellation, the coordinator uses `reset-stage` to hand the
same ticket to a fresh instance. It preserves the entire agent workspace, so
the new instance resumes from its durable records and queue state.

`application-metrics` runs before `kubernetes-metrics`. The application stage
stores the exact non-empty namespace set in a local scope evidence file and
publishes only its absolute path, SHA-256 digest, and count in
`application-metrics.yaml` under `namespace_scope`. The Kubernetes ticket must
take `application-metrics` as a direct input and repeat that exact reference
and digest. This permits multiple namespaces without allowing a cluster-wide
fallback. Namespace values remain in the local scope evidence file, never in a
ticket body or visible response.

## Checkpoint protocol

Use Mike Farah `yq` v4 for YAML creation and mutation. If it is unavailable or
not v4, return a `MISSING_YQ` failure report instead of falling back to a large
write-tool call.

Run executable repository scripts directly; their shebang selects Python. For
example, use `scripts/stage_check.py`, not `python3 scripts/stage_check.py`.

This is an agent-write rule, not a restriction on implementation language:

- When an agent directly creates or changes a YAML job ticket, state,
  checkpoint, stage artifact, or failure report, it MUST perform that write with
  `yq`. It MUST NOT use a generic write/edit tool, heredoc, Python one-liner, or
  hand-built YAML string for that direct write.
- Checked-in deterministic helper and validation scripts may be implemented in
  Python. A script may read or write files itself; callers are not required to
  replace sound Python file handling with shell or `yq` internals.
- Jsonnet source, rendered JSON, raw API/metric evidence, and binary files use
  their format-appropriate tools. Do not route non-YAML formats through `yq`
  merely to satisfy this rule.

- Write a record as soon as one logical unit is understood. Do not retain a
  growing result set in context for a final dump.
- Use one file per metric family, approved/rejected metric, question, panel,
  query, finding, or validation result. Keep each structured record at most
  8 KiB; put large/raw bodies in `evidence/` and reference their paths.
- Give files sortable neutral names such as `0001-M001.yaml` or
  `0007-T003.yaml`. Never put target endpoints, customer, cluster, environment,
  or credential material in a filename.
- Write to `tmp/`, validate with `yq`, then rename into `records/` or `outbox/`.
  A promoted record is immutable. Corrections create a new revision; they do
  not edit a file already consumed downstream.
- Metric analysts use `records/pending/` as the queue of unprocessed
  metric-family work items and `records/done/` for processed items. Run
  `scripts/metric_queue.py reconcile` before processing. After a metric record
  is durable, run `scripts/metric_queue.py complete <pending-item> <record>`.
  A pending item without a completed state entry remains eligible for processing.
  For discovery that has no exposition snapshot, create a bounded pending YAML
  work item before inspection. Leave a snapshot `manifest.yaml` in `pending/`;
  it is queue metadata, not a work item.
- Update only the agent-owned `state.yaml`. It records pending/completed IDs,
  record paths, digests, and the next action—not prose history or raw evidence.
- Before returning a completed artifact, set `state.status` to its `DONE`,
  `PASS`, `FAIL`, or `BLOCKED` status, clear `pending`, and set `next_action` to
  `complete`.
- On resume, inspect `state.yaml` and filenames with `yq`/`find`. Load only the
  next required record. Do not read every record into context at once.
- Do not open a large upstream stage artifact wholesale. Validate it
  mechanically, enumerate only IDs with `yq`, and project one required item at a
  time into the current agent's `tmp/` or context. For example:

  ```bash
  upstream_artifact="${UPSTREAM_ARTIFACT:?set upstream artifact path}"
  yq eval '.metrics[].id' "$upstream_artifact"
  export METRIC_ID=M001
  yq eval '.metrics[] | select(.id == strenv(METRIC_ID))' \
    "$upstream_artifact"
  unset METRIC_ID
  ```

  Use the corresponding bounded array (`approved`, `questions`, `queries`, or
  `findings`) for later stages.

Create a small YAML record atomically:

```bash
agent_run_dir="${DASHBOARD_AGENT_RUN_DIR:?set agent run directory}"
mkdir -p "$agent_run_dir/records/metrics"
export RECORD_ID=M001 RECORD_TYPE=gauge
draft="$agent_run_dir/tmp/0001-M001.yaml"
final="$agent_run_dir/records/metrics/0001-M001.yaml"
yq -n \
  '.id = strenv(RECORD_ID) | .type = strenv(RECORD_TYPE) | .limitations = []' \
  > "$draft"
yq eval '.' "$draft" >/dev/null
mv "$draft" "$final"
unset RECORD_ID RECORD_TYPE
```

Update the progress snapshot after the record is durable:

```bash
agent_run_dir="${DASHBOARD_AGENT_RUN_DIR:?set agent run directory}"
export RECORD_REF=records/metrics/0001-M001.yaml
yq -i \
  '.completed = ((.completed // []) + [strenv(RECORD_REF)] | unique) |
   .next_action = "inspect-next-item"' \
  "$agent_run_dir/state.yaml"
unset RECORD_REF
```

`yq -i` uses a temporary output before replacing the file, but it is still
restricted to the single-writer `state.yaml`; it is not a multi-writer lock.

## Stage assembly

The stage artifact is YAML in `outbox/`. Assemble its bounded arrays from the
small immutable records with `yq`; never reproduce all records in a write-tool
argument. For example:

```bash
agent_run_dir="${DASHBOARD_AGENT_RUN_DIR:?set agent run directory}"
yq eval-all \
  '. as $item ireduce ([]; . + [$item])' \
  "$agent_run_dir"/records/metrics/*.yaml \
  > "$agent_run_dir/tmp/metrics.yaml"

export ITEMS_FILE="$agent_run_dir/tmp/metrics.yaml"
yq -n \
  '.schema_version = 1 |
   .artifact_type = "application-metrics" |
   .metrics = load(strenv(ITEMS_FILE))' \
  > "$agent_run_dir/tmp/application-metrics.yaml"
unset ITEMS_FILE
```

Add the remaining required envelope and artifact fields using `yq`, then run
`scripts/stage_check.py --draft`. It validates the assigned
`tmp/<artifact>.yaml` using the ticketed inputs, support artifacts, evidence
base path, and repository working directory. Do not call
`validate_agent_workspace.sh` or `validate_workflow_artifact.py` directly and
do not reconstruct their arguments. After a `PASS` draft result, atomically
rename it to `outbox/<artifact>.yaml`, finish `state.yaml`, and run
`scripts/stage_check.py` for the terminal response. The
artifact remains the digest-bound stage gate; the record files are its
human-reviewable construction log and recovery snapshots.

Run contracts, stage artifacts, failure reports, job tickets, state, and
structured records are YAML and use `.yaml` filenames. There is no JSON or
`.yml` workflow-artifact compatibility mode. Rendered Grafana dashboards remain
JSON and Grafonnet source remains Jsonnet.

## Large metrics exposition

Never load a complete `/metrics` response into agent context. The initialized
application-metrics workspace provides `./metrics-sync`, which validates the
ticket and performs the fixed acquisition/snapshot operation:

```bash
cd <application-metrics-agent-run-directory>
./metrics-sync
```

The sync command invokes the internal reader and snapshot parser. The parser
has no URL, credential, or input-file option: exposition bytes enter only
through stdin. It emits no raw sample or label values to stdout. It writes one
small YAML snapshot per family plus `manifest.yaml`, preserving declared
`HELP`, `TYPE`, and `UNIT`, member and label names, sample counts, line
references, timestamp/exemplar presence, and bounded parse warnings.

On a new application-metrics run, `records/pending/` must not exist before this
command: the snapshot tool creates it atomically. Do not run
`metric_queue.py reconcile` or create that directory first. On a resumed run,
when `records/pending/manifest.yaml` already exists, do not fetch or snapshot
again; run `scripts/metric_queue.py reconcile` before processing its remaining
items. An empty `records/pending/` without a manifest is an interrupted initial
setup: recover with `rmdir records/pending`, then take the snapshot. Any
non-empty directory without a manifest is an unknown state and must fail rather
than be deleted.

These are discovery snapshots, not approved metric records. Analysts still
verify semantics, lifecycle, stored labels, availability, category, and risks.
In particular, `scripts/snapshot_metrics.py` preserves declared type literally and never infers a
counter from `_total` or another name suffix.
