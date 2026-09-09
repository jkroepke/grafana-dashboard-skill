# Deterministic workflow roadmap

The normal path must use a model only for decisions that need judgment:
operational questions and panel intent, ambiguous metric meaning, and `CUSTOM`
PromQL. A model cannot create a `PASS` merely by claiming a check happened.

## Phase 1 — facts and handoffs (implemented)

`metrics-sync` owns fresh versus resumed application-metric collection. It
eliminates the first-run conflict where queue setup accidentally pre-created the
snapshot output directory. `metric_facts.py` turns snapshot records into a
bounded `NEEDS_AI` inventory without category/name heuristics.

Coordinator dispatch is workspace-relative and ticket validation defaults to
the local `inbox/job.yaml` for specialist-local commands. Control commands
remain explicit because they intentionally target another run or agent.

Acceptance: a new application stage runs `./metrics-sync`, then
`scripts/metric_facts.py`, without an agent deciding how to invoke readers or
create the queue.

## Phase 2 — routine queries and probes (implemented)

`promql_templates.py` is a closed compiler for typed, standard forms. It
requires an explicit metric type and rejects counter functions for gauges,
unknown templates, and complex joins. Its request and result are JSON so exact
expression bytes are durable and reviewable.

`prometheus_probe_matrix.py` executes declared, concrete query/variable
probes. It writes raw target responses locally and derives status, warnings,
series count, returned labels, and duplicate declared identities. A reviewer
only interprets failures and `CUSTOM` query semantics.

Acceptance: standard packs use compiler output plus a PASS matrix report;
`CUSTOM` records retain the existing independent semantic review.

## Phase 3 — dashboard construction (next project-specific compiler)

Dashboard construction is deterministic once the plan is closed, but its
source must use the repository's pinned Grafonnet builders. Do not add a generic
JSON serializer: it would violate the builder-composition contract and cannot
preserve project helpers or focused-update content safely.

Add a project-pinned compiler only after its declarative model is fixed:

1. Define a closed panel model containing panel kind, visualization, unit,
   placement, field configuration, and query consumer IDs.
2. Compile the model and reviewed query pack through the vendored V2 builders.
3. Permit only additions/replacements declared by the plan; retain unrelated
   baseline content byte-semantically.
4. Render and run the existing integrity/parity/preservation gate.

Acceptance: compiler output and a hand-authored equivalent render identically;
unsupported visualization/layout transformations fail as `CUSTOM_BUILD` rather
than becoming a free-form source edit.

## Phase 4 — target validation and publish (implemented)

`grafana_dry_run.py --operation UPDATE` now performs GET, copies only required
live identity/folder/resource-version metadata, replaces the candidate spec,
and dry-run PUTs the item route. `grafana_publish.py` applies the same
create-or-update transaction after ticket, review, promotion, and integrity
preflight. It GETs readback, reruns structural/query checks, writes bounded raw
evidence, and creates either the digest-bound terminal publish report or a
deterministic failure report.

Acceptance: the publisher never constructs a mutable request in model context;
an update never falls back to create after an error.

## Phase 5 — evidence-bound approvals (next schema revision)

Add digest fields for the compiler result, probe report, dry-run response, and
publish readback to the query/review artifacts. Make PASS require those exact
machine-produced reports when the respective capability is enabled. Retain an
explicit `UNVERIFIED` path only when a run contract says access is unavailable.

This is deliberately a schema revision, not a compatibility-breaking hidden
field: it changes contracts, tickets, fixtures, and all existing retained
dashboard artifacts together.
