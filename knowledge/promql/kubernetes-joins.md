# Kubernetes PromQL joins

## Pod to workload ownership

Prefer kube-state-metrics owner relationships over pod-name regexes.

For Deployments, pod ownership usually passes through ReplicaSets:

```text
Pod -> ReplicaSet -> Deployment
```

Resolve each relationship with the exact KSM metric/labels available in the local datasource. Do not assume metric versions or label names without local evidence.

StatefulSet and DaemonSet ownership may have different direct relationships; inspect local KSM metrics.

## Application labels versus KSM labels

Application scrape-time labels in this environment:

```text
kubernetes_namespace
kubernetes_pod_name
```

Native KSM/cAdvisor labels normally use:

```text
namespace
pod
container
```

Do not join by labels that merely have similar meanings without explicit normalization or a common verified identity.

## Resource comparisons

For container usage/request/limit joins, keep:

```text
(namespace,pod,container)
```

and cluster identity when required.

Filter the same container population on both sides before aggregation.

## Workload-wide replica metrics

Replica metrics are workload-wide. A dashboard pod subset does not change desired replicas. Label panels accordingly rather than implying they are recalculated for selected pods.

## Replacement pods

Pod replacement often changes the `pod` label and therefore creates a new series. Do not interpret this as a reset in the previous pod's series.
