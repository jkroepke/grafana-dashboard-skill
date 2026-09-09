---
name: kubernetes-metrics
description: Deprecated model-role descriptor; Kubernetes/Istio candidates are emitted by the deterministic coordinator stage.
mode: subagent
tools: read, bash
---

# Kubernetes Metrics Stage

## Purpose

The coordinator's checked `./workflow dispatch` command executes this stage directly with the fixed
`kubernetes_presets.py` helper
and accepts its response automatically. Do not dispatch a model for it.

## Required workflow

The script validates the application namespace-scope binding, emits the fixed
catalogue, checkpoints records, validates the terminal artifact, and returns
the response. The following are catalogue limitations for downstream review:

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
