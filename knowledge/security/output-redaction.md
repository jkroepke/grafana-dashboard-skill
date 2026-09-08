# Confidentiality and visible-output redaction

Read this file before using any configured datasource, dashboard API, target-system access, or environment-specific resource identifiers.

## Hard rule

Sensitive target information may be used internally to perform the task, but it MUST NOT appear in visible agent text, subagent output, visible shell commands, command previews, diagnostic ledgers, review findings, or completion summaries.

Treat all of the following as sensitive unless the user explicitly says otherwise:

- endpoint URLs, hostnames, domains, FQDNs, IP addresses, ports, and proxy/jump-host addresses
- organization-, customer-, environment-, or application-identifying host/domain fragments
- application/service names and target-identifying metric prefixes, metric names, label values, workload names, namespaces, and selectors when they reveal target identity
- dashboard/resource names, UIDs, generated IDs, folder identifiers, and unrelated resource IDs discovered during probing
- cluster names, environment names, internal repository names, and local paths when they reveal target identity
- credentials, tokens, cookies, authorization headers, session data, netrc contents, credential-file contents, and secret environment-variable values

Do not repeat a sensitive literal merely because it already appeared in local input, command output, an API response, a previous agent message, or an error body.

## Visible command discipline

Commands shown in an agent transcript are visible output. They MUST be sanitized before execution/presentation.

Never place a literal target endpoint or sensitive resource identifier directly in a visible command.

Use opaque preconfigured references instead, for example:

```bash
$GRAFANA_URL/apis/dashboard.grafana.app/v2/namespaces/default/dashboards/$DASHBOARD_ID
$PROMETHEUS_URL/api/v1/query
```

The variables above are placeholders for an already configured value. Do not assign the sensitive value in the same visible command.

Preferred access patterns, in order:

1. existing authenticated wrapper that already knows the target
2. preconfigured environment variable whose value is not echoed
3. protected local configuration/credential file read by the command without printing its contents

## Opaque local access commands

When a target is reachable only through a local command, treat that command as
the access boundary. Receive its shell-free argv as an opaque task input; never
replace it with direct `curl`, a guessed URL, or an environment/configuration
scan. Execute the supplied argv as provided; it may invoke an access wrapper
such as `curl` or `kcurl` and contain its required opaque arguments. Never echo
the resolved argv, target, credential, or target identifier.

For Grafana `/version`, use a preconfigured zero-argument opaque executable;
do not construct its endpoint or supply target arguments. It runs once. Its
exit status `0` must mean it received HTTP 200 and writes the JSON response to
stdout. Redirect stdout and stderr to neutral scratch files, inspect only
`gitTreeState` locally, and do not echo the command's resolved configuration,
stdout, or stderr into visible tool output.

Never use or enable shell tracing for target-access commands. Avoid `set -x`, `env`, `printenv`, `echo "$TOKEN"`, `echo "$URL"`, `cat` of credential files, or equivalent output that reveals values.

If a wrapper requires a URL argument, construct it from an already configured non-echoed variable. Do not paste the literal target into the command transcript.

If a query or command argument contains target-identifying metric names, label values, resource names, or selectors, store that query/request in a neutral scratch file and pass the file to the command. Do not paste the sensitive expression into the visible command line.

Use neutral scratch paths such as `/tmp/query-A.json`, `/tmp/request-B.json`, or repository-provided temporary paths. Do not encode application, customer, cluster, namespace, or resource names in scratch filenames.

## Response and error handling

Server responses and errors can echo sensitive target values. Before returning evidence to another agent or the user:

- extract only the schema/error fields needed for diagnosis
- replace sensitive literals with stable placeholders
- keep raw response bodies in local scratch files
- return the scratch path only when another local agent needs targeted inspection
- never paste response headers that can contain endpoints, cookies, authorization data, or infrastructure identifiers
- do not paste full PromQL when its metric names/selectors reveal target identity; return a neutral query ID or scratch-file path instead

Use placeholders consistently:

```text
<TARGET>
<TARGET_URL>
<DATASOURCE>
<DASHBOARD_ID>
<RESOURCE_ID>
<CLUSTER>
<ENVIRONMENT>
<APPLICATION>
<METRIC>
<QUERY_ID>
```

A placeholder should preserve the semantic role, not the sensitive value.

## Subagent handoff

The coordinator MUST NOT pass literal connection details or unrelated discovered resource identifiers to subagents.

Pass only:

- an opaque access alias/wrapper instruction
- the capability allowed, such as `read-only datasource query` or `Dashboard V2 dry-run`
- local scratch-file paths containing already sanitized evidence when sufficient
- neutral query IDs/scratch paths instead of target-identifying PromQL when the exact expression can remain on disk

When a subagent needs to execute target access, it follows the same visible-command discipline and MUST NOT echo resolved connection values.

## Dashboard content versus transcript

A generated dashboard source file may need real metric names, selectors, resource names, or datasource references to work. That does not authorize echoing those values in the visible conversation.

Keep operational identifiers inside the intended local artifact/API payload when required. In visible summaries use generic descriptions such as:

- `application dashboard`
- `target namespace`
- `selected workload`
- `target Grafana`
- `configured Prometheus datasource`
- `application metric`
- `validated query Q1`

Keep target-identifying query text inside the digest-bound query pack. Specialists communicate only its neutral path, query ID, and digest. The coordinator routes those references and MUST NOT copy, reconstruct, repair, or quote the query text.

Do not include resource names/UIDs in completion output unless the user explicitly asks for a specific identifier and disclosure is allowed by the task's confidentiality requirements.

## Review rule

Any visible leakage of sensitive target information is a review failure even when the dashboard itself is technically correct.

The reviewer MUST return `FAIL` when source execution or review output exposes sensitive target information in visible text or commands. The required correction is to use opaque access references and sanitized evidence, then repeat the affected validation without exposing the literal values.
