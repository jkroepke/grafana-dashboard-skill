# Diagnostic execution discipline

Read this file before running more than one diagnostic command for the same Grafana Dashboard V2 validation failure.

The goal is to keep troubleshooting evidence-driven and bounded. Do not spend context narrating intended commands.

## Hard rules

- MUST execute a diagnostic action immediately after deciding it is needed.
- MUST NOT emit repeated self-dialogue such as `Let me ...`, `Wait ...`, `Actually ...`, `I will ...`, or repeated descriptions of the same next command.
- MUST NOT state the same intended action twice without new tool/command output between the statements.
- If the same intended action has been stated twice without execution, stop narrating and execute it. If execution is impossible, report the concrete blocker.
- One diagnostic step is atomic: **hypothesis -> one changed candidate -> one command/request -> one result -> one recorded fact**.
- MUST NOT rerun the exact same request body against the exact same endpoint unless reproducing determinism is the explicit purpose.
- MUST change only one logical dimension per probe, or use a documented binary split of a larger group.
- MUST preserve proven facts. Do not reopen a hypothesis that already passed with the exact same serialized subtree unless a later interaction test provides new evidence.
- MUST NOT create a new helper script merely because the previous helper had a quoting mistake. Prefer simpler shell/`jq` transformations; switch implementation method at most once for the same probe.
- MUST NOT patch the final rendered dashboard for a fix. Diagnostic copies are temporary; corrections go back to Jsonnet/Grafonnet source.
- MUST stop after **6 target-side isolation probes for one validation failure**. If the root cause is still unresolved, return `FAIL` with the diagnostic ledger instead of continuing indefinitely.

The 6-probe budget excludes the initial failing full-dashboard dry-run and the final full-dashboard verification after a source fix.

## No narration loop

Bad:

```text
Let me test the annotation.
Let me build the annotation test.
Let me create the script.
Let me run it now.
Let me do it.
Let me create it.
```

Correct behavior:

```text
Hypothesis: annotations trigger the failure.
<execute one command>
Result: PASS/FAIL + exact evidence.
```

Prefer no pre-command prose at all when the runtime already shows commands/tool calls.

## Diagnostic ledger

After the first failed dry-run, keep a compact ledger in scratch state or a temporary file. Do not repeatedly reconstruct history from conversation text.

Use this shape:

```text
# | Candidate delta                     | Result | Proven fact
0 | full dashboard                      | FAIL   | baseline error: <short exact error>
1 | layout + elements                   | PASS   | exact layout/elements accepted
2 | + variables                         | PASS   | exact variables accepted with layout/elements
3 | + annotations                       | FAIL   | failure introduced by annotations or interaction
4 | annotation half/minimal annotation  | ...    | ...
```

A `PASS` establishes a monotonic fact for the exact serialized subtrees in that candidate.

Example:

- if `layout + elements` passes, do not continue claiming that the layout itself is unsupported
- if `layout + elements + variables` passes, do not retest those same variables unchanged
- if adding annotations changes PASS -> FAIL, investigate the annotation or its interaction next

Do not promote the ledger to user-facing output unless the root cause remains unresolved.

## Isolation state machine

Use this order. Do not improvise a new plan after every result.

### State 0: Baseline

Capture once:

- exact rendered candidate
- exact endpoint/query parameters
- complete response
- short normalized error

Record it as ledger row `0`.

### State 1: Minimal structural probe

Build the smallest target-valid candidate that retains the suspected structure.

For a layout problem, retain only what is required to validate the layout and referenced elements.

Dry-run once.

- FAIL -> inspect the selected schema branch
- PASS -> mark that exact structure as accepted and move on

### State 2: Add feature groups

Add whole feature groups in a fixed order until PASS becomes FAIL. For a Dashboard V2 candidate, useful groups are:

1. variables
2. annotations
3. dashboard-level optional fields (`description`, `editable`, `tags`, `cursorSync`, `preload`, `links`, time settings)
4. remaining panel/query complexity if not already included

Do not test groups already proven by an earlier candidate.

### State 3: Binary split the failing group

When one group changes PASS -> FAIL:

- split that group roughly in half
- test one half once
- continue only in the failing half

Do not remove/add unrelated fields randomly.

### State 4: Source correction

Once the exact invalid field/composition is proven:

1. fix Jsonnet/Grafonnet source
2. render normally
3. run local checks
4. run the full target strict dry-run once

If the full candidate now passes, continue review.

If it fails with a **different** error, start a new ledger for that new failure. Do not mix the two diagnoses.

### State 5: Stop unresolved

Stop when:

- 6 isolation probes have been used without isolating the cause
- the same request/result has repeated without new evidence
- required target evidence is unavailable
- the next step would be speculative rather than discriminating

Return `FAIL` with:

- baseline error
- the compact probe ledger
- what is proven accepted
- the smallest remaining failing group
- exact missing evidence

## Prefer structural slicing over helper programs

For diagnostic copies of rendered JSON, prefer `jq` because it avoids quoting/code-generation loops.

Example: retain exact layout/elements and the first variable from the rendered candidate:

```bash
jq '
  {
    apiVersion,
    kind,
    metadata: {name: "dry-run-probe"},
    spec: {
      title: "Dry-run probe",
      elements: .spec.elements,
      layout: .spec.layout,
      variables: [ .spec.variables[0] ]
    }
  }
' rendered-dashboard.json > /tmp/dashboard-v2-probe.json
```

When adding a previously omitted group, copy the exact group from the rendered candidate rather than reconstructing its fields from memory.

Example:

```bash
jq --slurpfile full rendered-dashboard.json '
  .spec.annotations = $full[0].spec.annotations
' /tmp/dashboard-v2-probe.json > /tmp/dashboard-v2-probe-next.json
```

Use Python only when the required transformation is genuinely clearer than `jq`.

If a shell/heredoc command fails because of quoting:

1. correct it once or switch to `jq`
2. execute
3. do not narrate repeated attempts

## Evidence wording

Use factual state transitions.

Good:

```text
Probe 2 PASS: the exact rendered layout, elements, and all three variables are accepted by target Grafana. The next untested group is annotations.
```

Bad:

```text
The layout error must be a red herring. Maybe Grafana is reporting another field under layout. Let me reconsider. Perhaps...
```

A passing reduced candidate proves only what it contains. Say `accepted in this candidate`, not `globally impossible to affect validation`.

## Reviewer completion

The reviewer should expose only the final review result, not its running self-dialogue.

If successful:

```text
PASS
```

If unresolved:

```text
FAIL

1. Target Dashboard V2 validation remains unresolved after bounded isolation.
   Evidence: <short baseline error>; probes: <compact ledger summary>.
   Proven accepted: <subtrees/groups>.
   Remaining failing scope: <smallest group>.
   Required correction/evidence: <specific next evidence, not a theory>.
```
