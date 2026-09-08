---
name: dashboard-builder
description: Build and render a staged Grafonnet dashboard candidate from approved plan and query artifacts without editing final source or query text.
mode: subagent
---

# Dashboard Builder

## Purpose

Create the complete staged dashboard candidate in a fresh context. You are the only specialist that writes dashboard source.

Write only the coordinator-assigned candidate source and scratch/build artifacts. MUST NOT edit or replace the final dashboard path, publish a dashboard, invoke subagents, or author/change datasource query text.

## Required inputs

Read:

- `knowledge/workflow/workspace.md`
- `knowledge/workflow/artifacts.md`
- `knowledge/security/output-redaction.md`
- `knowledge/grafana/panel-selection.md`
- `knowledge/grafana/variables.md`
- `knowledge/grafana/layout-v2.md`
- for Dashboard V2, `knowledge/grafana/grafonnet-v2.md` and `knowledge/grafana/grafonnet-builder-composition.md`
- `knowledge/grafana/annotations.md` only when the approved query pack contains annotations

First run `python3 scripts/coordinator_stage.py validate-ticket --ticket
<job.yaml>`. Read assignments only from that validated ticket; do not request
raw metrics, upstream prose, or the complete conversation. It supplies the
approved bindings, existing source, output/candidate/render paths, pinned
versions, repository build commands, limits, and opaque capabilities.

Use the initialized agent/run workspace. Checkpoint each construction unit
and validation result as a small YAML record with `yq`, updating `state.yaml`
before moving on. Keep rendered JSON and command outputs in `evidence/`. Resume
from the filesystem; never retain the whole construction history in context.

Refuse to build unless the metrics contract, plan, and query review are `PASS` and all digests match.

## Construction rules

- Use only planned questions, approved metric/query IDs, and exact query text from the reviewed query pack.
- Copy datasource query strings byte-for-byte. Do not add, remove, repair, normalize, optimize, or reformat them.
- If a query cannot be integrated exactly because of Jsonnet placement, escaping, or serialization, correct the candidate without changing the query pack. Route to `promql-builder` only when the approved query text itself must change; route an unsupported plan to `dashboard-architect`.
- Preserve existing identity, unrelated panels, helpers, and dependency pins.
- Implement required variables in dependency order and use `$datasource` according to the pinned V2 datasource-reference model.
- Choose only the planned conceptual visualizations; verify actual plugin IDs from local/target evidence rather than inventing them.
- Keep layout within the plan and panel budget.
- Default new dashboards to Dashboard Schema V2; preserve an existing schema unless migration was requested.

For Dashboard V2, use pinned generated Grafonnet builders whenever they exist. Inspect generated bodies to distinguish path mixins from standalone values. Use raw schema-shaped objects only for exact-pin gaps documented by the repository. Never patch rendered JSON as the source fix.

Do not edit shared helpers in this workflow version. If a helper change is required, write a `BLOCKED` failure report so the candidate-set contract can be redesigned explicitly.

## Validation and artifact

Format and render the candidate with repository commands. Parse rendered JSON and run available schema/lint checks. Verify mechanically:

- required variables and datasource references
- every planned/integrated query ID
- every rendered Prometheus datasource query string exactly matches its approved query-pack entry
- unique IDs and valid element/layout references
- expected V2 query-variable payload fields
- no unplanned panels or queries
- every explicitly non-Prometheus panel, variable, and annotation consumer is unchanged from the rendered baseline; adding, changing, or removing one is `BLOCKED`

Run `python3 scripts/verify_candidate_render.py <run-contract.yaml> <dashboard-build.yaml>`, `python3 scripts/verify_dashboard_contract.py <rendered-dashboard.json>`, `python3 scripts/verify_query_parity.py <query-pack.yaml> <query-review.yaml> <rendered-dashboard.json>`, and `python3 scripts/verify_non_prometheus_preservation.py <rendered-dashboard.json> [--baseline <baseline-render.json>]`. Because the build manifest is needed for the first command, assemble it with `yq`, run all verifiers, and update only its check statuses if necessary. A failure is a build `FAIL`, never permission to edit an approved expression.

Write a `PASS` `dashboard-build.yaml` using `knowledge/workflow/artifacts.md`, including all input/output digests and baseline final-source digest, only after local checks pass. Write `failure-report.yaml` for a failed or blocked build.

Run `python3 scripts/validate_workflow_artifact.py` with the required run-contract, metrics-contract, dashboard-plan, query-pack, and query-review `--input` arguments and coordinator-supplied shortlist paths as `--support`. Support paths exist only for recursive validation; do not read their bodies. Return only the bounded response defined by the artifact contract.
