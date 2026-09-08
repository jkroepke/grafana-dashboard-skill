# Filesystem workspace and YAML queue

Use the repository filesystem as durable working memory. Agent context is a
cache, not the system of record.

## Required layout

The coordinator selects a filesystem-safe `<project-name>` and a neutral
`<run-id>`. Every role works below its own directory:

```text
dashboards/<project-name>/workspace/<agent>/<run-id>/
├── inbox/       immutable job tickets from the coordinator
├── records/     small structured findings, one logical item per YAML file
├── evidence/    raw or sanitized evidence kept out of YAML records
├── outbox/      completed stage artifact or failure report
├── tmp/         incomplete files; never hand these to another stage
└── state.yaml   small resumable progress snapshot
```

Initialize the directory with:

```bash
scripts/init_agent_workspace.sh \
  <repository-root> <project-name> <run-id> <agent>
```

Before assembling or returning a stage artifact, validate the checkpoint area:

```bash
scripts/validate_agent_workspace.sh <agent-run-dir>
```

The validator rejects missing layout/state, inbox/record symlinks, non-YAML
structured files, invalid/non-mapping YAML, inbox/record files over 8 KiB, and
state over 16 KiB. When an outbox contains a terminal stage artifact, the
validator also requires `state.status` to equal the artifact status and
`state.next_action` to be `complete`, `pending` to be empty, and `completed` to
contain the terminal artifact path. A coordinator run contract alone is not a
terminal artifact.

The coordinator writes one immutable, at-most-8-KiB `inbox/job.yaml` before
dispatch. It contains the run/stage/revision, approved input paths and digests,
assigned output paths, budgets, and opaque capability references required by
that role. It contains no artifact bodies or raw evidence. The dispatch prompt
contains only the agent ID plus the job-ticket path and digest; it does not
repeat the job contents in model context.

A job ticket uses this bounded shape; unused maps/lists stay empty rather than
growing the dispatch prompt:

```yaml
schema_version: 1
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
outputs:
  artifact: outbox/application-metrics.yaml
  candidate: null
  rendered: null
limits: {}
capability_refs: []
```

Relative paths are resolved from the project `workspace/` root; paths may be
absolute when required by an artifact contract. Every digest is computed from
the exact referenced bytes. The specialist validates the ticket and all
declared digests before processing its first queue item.

After dispatch, only the assigned specialist writes in `records/`, `evidence/`,
`tmp/`, `outbox/`, and its `state.yaml`. No two agents write the same file.
Downstream stages read approved `outbox/` artifacts and selected record files;
they never edit them.

## Checkpoint protocol

Use Mike Farah `yq` v4 for YAML creation and mutation. If it is unavailable or
not v4, return a `MISSING_YQ` failure report instead of falling back to a large
write-tool call.

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

Never place sensitive values directly in a visible command. When a record needs
target-derived content, load it from an already-written private local evidence
file and emit only the permitted sanitized projection.

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

Add the remaining required envelope and artifact fields using `yq`, run the
workspace validator and complete artifact validator, then atomically rename it
to `outbox/<artifact>.yaml`. The
artifact remains the digest-bound stage gate; the record files are its
human-reviewable construction log and recovery snapshots.

Run contracts, stage artifacts, failure reports, job tickets, state, and
structured records are YAML and use `.yaml` filenames. There is no JSON or
`.yml` workflow-artifact compatibility mode. Rendered Grafana dashboards remain
JSON and Grafonnet source remains Jsonnet.

## Large metrics exposition

Never load a complete `/metrics` response into agent context. Stream Prometheus
or OpenMetrics text through the repository helper:

```bash
agent_run_dir="${DASHBOARD_AGENT_RUN_DIR:?set agent run directory}"
metrics_input="${METRICS_INPUT:?set private metrics input path}"
python3 scripts/snapshot_metrics.py \
  --output-dir "$agent_run_dir/records/exposition" \
  --source-ref metrics-evidence < "$metrics_input"
```

For live access, pipe the output of the configured opaque metrics reader into
the same command. `snapshot_metrics.py` intentionally has no URL, credential,
or input-file option: exposition bytes enter only through stdin. It emits no raw
sample or label values to stdout. It writes one small YAML snapshot per family
plus `manifest.yaml`, preserving declared `HELP`, `TYPE`, and `UNIT`, member and
label names, sample counts, line references, timestamp/exemplar presence, and
bounded parse warnings.

These are discovery snapshots, not approved metric records. Analysts still
verify semantics, lifecycle, stored labels, availability, category, and risks.
In particular, the helper preserves declared type literally and never infers a
counter from `_total` or another name suffix.
