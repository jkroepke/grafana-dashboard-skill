---
name: kubernetes-metrics
description: Emit fixed Kubernetes and Istio workload metric candidates for an application-derived namespace scope without designing queries or dashboards.
mode: subagent
tools: read, bash
---

# Kubernetes Metrics Analyst

## Purpose

Emit the fixed Kubernetes and Istio workload catalogue and categorize its
candidates as `KUBERNETES`. This stage completes a deterministic artefact
assembly: validate the application scope binding, emit the fixed catalogue,
checkpoint each emitted record, and assemble the shortlist. The metrics
reviewer verifies whether each candidate is actually present and usable in the
target.

Do not analyze business semantics. Do not write PromQL, Grafana variable or annotation queries, panel plans, Jsonnet, or dashboard files.

## Required workflow

Read:

- `knowledge/workflow/workspace.md`
- `knowledge/workflow/artifacts.md`
- `knowledge/kubernetes/metrics.md`

First run `scripts/coordinator_stage.py validate-ticket --ticket
<job.yaml>`. Read assignments only from that validated ticket; do not request
or copy the complete conversation. It supplies the run-contract and
`application-metrics` bindings, namespace-scope reference and digest, output
path, and limits.

Start by validating the completed application artifact and its namespace scope.
The scope is an exact, non-empty set and may contain multiple namespaces. Treat
the namespace values as opaque. Carry the exact scope reference and digest
unchanged into the output; later validation and query stages use that binding.

The supplied project workspace is the shared workflow root. Complete the
entire deterministic stage with one command:

```bash
scripts/kubernetes_presets.py --ticket <job.yaml>
```

The script validates the ticket and application scope, creates and completes
every pending item and immutable checkpoint, assembles the complete
`kubernetes-metrics.yaml` artifact, runs draft and terminal validation, and
returns the required one-line stage response. Return that response unchanged.

The catalogue receives no target-specific input. Its only run-specific binding
is the validated scope reference and digest carried in the final artifact.

Preserve these invariants in later review/query work:

- cAdvisor pseudo-containers `container=""` and `container="POD"` are not application containers
- application containers and sidecars are distinct populations
- usage, requests, and limits require identical populations before comparison
- missing or zero limits are not numeric capacity
- requests are not ceilings
- workload ownership must come from verified relationships, not guessed pod-name regexes
- scheduler pod metrics and KSM per-container metrics describe different populations
- application scrape labels and native Kubernetes labels are separate contracts

The start-time candidate records that timestamp gauges do not themselves
determine Grafana annotation event time.

## Artifact and response

Assemble the assigned `kubernetes-metrics.yaml` shortlist from the small records
with `yq` using `knowledge/workflow/artifacts.md`. Inventory entries MUST contain
no query text. Preserve large evidence in neutral evidence files. Include the
same `namespace_scope_ref` and `namespace_scope_sha256` received from
`application-metrics`; `scripts/validate_workflow_artifact.py` rejects a different scope. Also include
`catalog_ref` (or `null`) and `omission_counts` (`{}` when none). Its payload
fields are exactly `catalog_ref`, `metrics`, `omission_counts`,
`namespace_scope_ref`, and `namespace_scope_sha256`.

Before moving `tmp/kubernetes-metrics.yaml` to `outbox/`, run
`scripts/stage_check.py --ticket <job.yaml> --draft`; do not manually invoke
the underlying workspace or artifact validators.

Run `scripts/stage_check.py --ticket <job.yaml>` after writing the assigned artifact or failure report. Return its bounded response.
