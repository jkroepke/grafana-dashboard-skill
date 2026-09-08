#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "usage: validate_agent_workspace.sh <agent-run-dir>" >&2
  exit 2
fi

agent_root=$1
for directory in inbox records evidence outbox tmp; do
  [ -d "$agent_root/$directory" ] || {
    echo "missing agent workspace directory: $directory" >&2
    exit 1
  }
done

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

state_path="$agent_root/state.yaml"
[ -f "$state_path" ] && [ ! -L "$state_path" ] || {
  echo "state.yaml must be a regular file" >&2
  exit 1
}
[ "$(wc -c < "$state_path")" -le 16384 ] || {
  echo "state.yaml exceeds 16384 bytes" >&2
  exit 1
}
yq eval -e 'tag == "!!map"' "$state_path" >/dev/null
yq eval -e '
  .schema_version == 1 and
  (.agent | tag == "!!str") and
  (.run_id | tag == "!!str") and
  (.status == "READY" or .status == "IN_PROGRESS" or .status == "DONE" or
   .status == "PASS" or .status == "FAIL" or .status == "BLOCKED") and
  (.completed | tag == "!!seq") and
  (.pending | tag == "!!seq") and
  (.next_action | tag == "!!str")
' "$state_path" >/dev/null || {
  echo "state.yaml has an invalid workflow state" >&2
  exit 1
}

for area in inbox records; do
  if find "$agent_root/$area" -type l -print -quit | grep -q .; then
    echo "inbox and record symlinks are not allowed" >&2
    exit 1
  fi
  if find "$agent_root/$area" -type f ! -name '*.yaml' -print -quit | grep -q .; then
    echo "structured inbox and records must use .yaml filenames" >&2
    exit 1
  fi

  find "$agent_root/$area" -type f -name '*.yaml' -exec sh -c '
    for record do
      if [ "$(wc -c < "$record")" -gt 8192 ]; then
        echo "workspace inbox/record exceeds 8192 bytes" >&2
        exit 1
      fi
      yq eval -e '\''tag == "!!map"'\'' "$record" >/dev/null || exit 1
    done
  ' sh {} +
done

terminal_artifact=
terminal_count=0
for artifact in "$agent_root"/outbox/*.yaml; do
  [ -e "$artifact" ] || continue
  artifact_type=$(yq eval '.artifact_type // ""' "$artifact")
  if [ "$artifact_type" = "run-contract" ]; then
    continue
  fi
  terminal_artifact=$artifact
  terminal_count=$((terminal_count + 1))
done

if [ "$terminal_count" -gt 1 ]; then
  echo "outbox contains more than one terminal artifact" >&2
  exit 1
fi
if [ "$terminal_count" -eq 1 ]; then
  terminal_status=$(yq eval '.status // ""' "$terminal_artifact")
  state_status=$(yq eval '.status' "$state_path")
  next_action=$(yq eval '.next_action' "$state_path")
  terminal_ref="outbox/$(basename "$terminal_artifact")"
  state_is_complete=no
  if [ "$(yq eval '.pending | length' "$state_path")" -eq 0 ] && \
     yq eval '.completed[]' "$state_path" | grep -Fqx "$terminal_ref"; then
    state_is_complete=yes
  fi
  if [ "$state_status" != "$terminal_status" ] || [ "$next_action" != "complete" ] || \
     [ "$state_is_complete" != "yes" ]; then
    echo "state.yaml does not match terminal outbox artifact" >&2
    exit 1
  fi
fi

echo "PASS agent-workspace"
