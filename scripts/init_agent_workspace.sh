#!/bin/sh
set -eu

if [ "$#" -ne 4 ]; then
  echo "usage: init_agent_workspace.sh <repository-root> <project-name> <run-id> <agent>" >&2
  exit 2
fi

repository_root=$1
project_name=$2
run_id=$3
agent_id=$4

safe_component() {
  case "$1" in
    ""|.|..|*[!A-Za-z0-9._-]*) return 1 ;;
    *) return 0 ;;
  esac
}

safe_component "$project_name" || {
  echo "project-name must be one filesystem-safe path component" >&2
  exit 2
}
safe_component "$run_id" || {
  echo "run-id must be one neutral filesystem-safe path component" >&2
  exit 2
}

case "$agent_id" in
  coordinator|application-metrics|kubernetes-metrics|metrics-reviewer|dashboard-architect|promql-builder|promql-reviewer|dashboard-builder|dashboard-reviewer|dashboard-publisher) ;;
  *)
    echo "unknown dashboard workflow agent" >&2
    exit 2
    ;;
esac

command -v yq >/dev/null 2>&1 || {
  echo "Mike Farah yq v4 is required" >&2
  exit 3
}
case "$(yq --version 2>/dev/null)" in
  *mikefarah/yq*" version v4."*) ;;
  *)
    echo "Mike Farah yq v4 is required" >&2
    exit 3
    ;;
esac

repository_root=$(cd "$repository_root" && pwd -P)
agent_root="$repository_root/dashboards/$project_name/workspace/$agent_id/$run_id"
umask 077
mkdir -p \
  "$agent_root/inbox" \
  "$agent_root/records" \
  "$agent_root/records/done" \
  "$agent_root/evidence" \
  "$agent_root/outbox" \
  "$agent_root/tmp"

physical_agent_root=$(cd "$agent_root" && pwd -P)
case "$physical_agent_root/" in
  "$repository_root/"*) ;;
  *)
    echo "agent workspace escapes repository root" >&2
    exit 2
    ;;
esac

tool_link() {
  link_path=$1
  target_path=$2
  if [ -L "$link_path" ]; then
    [ "$(readlink "$link_path")" = "$target_path" ] || {
      echo "workflow tool link has an unexpected target" >&2
      exit 2
    }
  elif [ -e "$link_path" ]; then
    echo "workflow tool link already exists" >&2
    exit 2
  else
    ln -s "$target_path" "$link_path"
  fi
}

tool_link "$agent_root/workflow" "$repository_root/scripts/workflow"
tool_link "$agent_root/stage-check" "$repository_root/scripts/stage_check.py"
tool_link "$agent_root/stage-finish" "$repository_root/scripts/stage_finish.py"

case "$agent_id" in
  application-metrics)
    tool_link "$agent_root/metrics-sync" "$repository_root/scripts/metrics_sync.py"
    tool_link "$agent_root/metric-facts" "$repository_root/scripts/metric_facts.py"
    tool_link "$agent_root/metrics-discovery" "$repository_root/scripts/metrics_discovery.py"
    tool_link "$agent_root/namespace-scope" "$repository_root/scripts/namespace_scope.py"
    tool_link "$agent_root/metric-record" "$repository_root/scripts/metric_record.py"
    tool_link "$agent_root/metric-queue" "$repository_root/scripts/metric_queue.py"
    tool_link "$agent_root/prometheus-reader" "$repository_root/scripts/prometheus_reader.py"
    tool_link "$agent_root/stage-failure-report" "$repository_root/scripts/stage_failure_report.py"
    ;;
  promql-builder)
    tool_link "$agent_root/promql-templates" "$repository_root/scripts/promql_templates.py"
    tool_link "$agent_root/query-work-partition" "$repository_root/scripts/query_work_partition.py"
    tool_link "$agent_root/query-record" "$repository_root/scripts/query_record.py"
    tool_link "$agent_root/stage-failure-report" "$repository_root/scripts/stage_failure_report.py"
    ;;
  dashboard-architect)
    tool_link "$agent_root/dashboard-capabilities" "$repository_root/scripts/dashboard_capabilities.py"
    tool_link "$agent_root/stage-failure-report" "$repository_root/scripts/stage_failure_report.py"
    ;;
  metrics-reviewer)
    tool_link "$agent_root/metrics-review-probes" "$repository_root/scripts/metrics_review_probes.py"
    tool_link "$agent_root/metric-disposition" "$repository_root/scripts/metric_disposition.py"
    tool_link "$agent_root/metrics-contract-assemble" "$repository_root/scripts/metrics_contract_assemble.py"
    tool_link "$agent_root/stage-failure-report" "$repository_root/scripts/stage_failure_report.py"
    ;;
  promql-reviewer)
    tool_link "$agent_root/prometheus-probe-matrix" "$repository_root/scripts/prometheus_probe_matrix.py"
    tool_link "$agent_root/query-review-context" "$repository_root/scripts/query_review_context.py"
    tool_link "$agent_root/query-review-capabilities" "$repository_root/scripts/query_review_capabilities.py"
    tool_link "$agent_root/stage-failure-report" "$repository_root/scripts/stage_failure_report.py"
    ;;
  dashboard-builder)
    tool_link "$agent_root/stage-failure-report" "$repository_root/scripts/stage_failure_report.py"
    ;;
  dashboard-reviewer)
    tool_link "$agent_root/stage-failure-report" "$repository_root/scripts/stage_failure_report.py"
    ;;
  dashboard-publisher)
    tool_link "$agent_root/grafana-publish" "$repository_root/scripts/grafana_publish.py"
    ;;
esac

state_path="$agent_root/state.yaml"
export AGENT_ID="$agent_id" RUN_ID="$run_id"
if [ -e "$state_path" ]; then
  yq eval -e \
    '.schema_version == 1 and .agent == strenv(AGENT_ID) and .run_id == strenv(RUN_ID)' \
    "$state_path" >/dev/null
else
  state_draft="$agent_root/tmp/state.yaml.$$"
  yq -n \
    '.schema_version = 1 |
     .agent = strenv(AGENT_ID) |
     .run_id = strenv(RUN_ID) |
     .status = "READY" |
     .completed = [] |
     .pending = [] |
     .next_action = "read-inbox"' \
    > "$state_draft"
  yq eval '.' "$state_draft" >/dev/null
  mv "$state_draft" "$state_path"
fi
unset AGENT_ID RUN_ID

printf '%s\n' "$agent_root"
