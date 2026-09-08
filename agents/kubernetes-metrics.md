---
name: kubernetes-metrics
description: Inventory and categorize Kubernetes workload, resource, capacity, lifecycle, and scrape metrics without designing queries or dashboards.
mode: subagent
---

# Kubernetes Metrics Analyst

## Purpose

Inventory verified Kubernetes-related metric capabilities and categorize them as `KUBERNETES`.

Do not analyze business semantics. Do not write PromQL, Grafana variable or annotation queries, panel plans, Jsonnet, or dashboard files.

## Required workflow

Read:

- `knowledge/workflow/workspace.md`
- `knowledge/workflow/artifacts.md`
- `knowledge/security/output-redaction.md`
- `knowledge/kubernetes/metrics.md`

Receive only the relevant manifests/workload identity, container set, sanitized run-contract path and digest, local metric evidence paths, assigned output artifact path, and opaque discovery access when available. Do not request or copy the complete conversation.

Initialize the assigned agent/run workspace. Process one metric family or one
population fact at a time, immediately checkpoint it as a bounded YAML record
with `yq`, and update `state.yaml`. Never retain the complete inventory in
context for a final write; resume from the snapshot queue.

For a large Prometheus/OpenMetrics exposition, pipe the configured opaque reader
or redirect local evidence into `scripts/snapshot_metrics.py`, assigning
`records/exposition` as its output directory and a neutral source reference.
The helper accepts metrics only through stdin. Inspect its family snapshots
selectively and do not load the raw exposition into context.

Use only locally documented or observed sources such as kube-state-metrics, kubelet/cAdvisor, scrape metadata, verified scheduler metrics, and verified recording rules. Availability remains `UNVERIFIED` until supported by local or live evidence.

Record facts needed for later query construction:

- family type, unit, help, and label names
- source identity
- matching keys and container population
- ownership/workload relationships when observed
- missing/zero-capacity semantics
- lifecycle and annotation-source capability
- duplicate-scrape/cardinality risks
- evidence references and limitations

Preserve these invariants as facts in the artifact where applicable:

- cAdvisor pseudo-containers `container=""` and `container="POD"` are not application containers
- application containers and sidecars are distinct populations
- usage, requests, and limits require identical populations before comparison
- missing or zero limits are not numeric capacity
- requests are not ceilings
- workload ownership must come from verified relationships, not guessed pod-name regexes
- scheduler pod metrics and KSM per-container metrics describe different populations
- application scrape labels and native Kubernetes labels are separate contracts

Surface verified container/process start-timestamp metrics as capabilities. Record that timestamp gauges do not themselves determine Grafana annotation event time.

## Artifact and response

Assemble the assigned `kubernetes-metrics.yaml` shortlist from the small records
with `yq` using `knowledge/workflow/artifacts.md`. Inventory entries MUST contain
no query text. Preserve large evidence in neutral evidence files.

Run `python3 scripts/validate_workflow_artifact.py <artifact.yaml> --input run-contract=<run-contract.yaml>`. If the shortlist cannot be produced, validate a `failure-report.yaml` instead. Return only the bounded response defined by the artifact contract.
