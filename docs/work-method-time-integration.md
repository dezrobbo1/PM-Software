# Headless Work-Method + Productive-Time Integration v0

## Purpose and owning boundary

Compose authorised structure, productive execution periods and executable resource
allocation in one small headless scheduling path. This follows PR #34's decision
to retain selective integrated assignment, not adopt its inconclusive pooled-
feedback replacement. No further resource-decomposition programme is started.

`project/work_method_time.py` owns a portable composition input:

- the existing native `WorkPackage` and `ExecutionMethod` definitions own structure;
- the existing productive project fields own calendars, processing ticks, named
  requirement slots, disjoint interchangeable group quantities and activities;
- existing reported/accepted outage records remain distinct; only accepted
  outages affect execution opportunity.

`processing_ticks` is the sole source of execution work. The structural validator
receives a generated view of those same activity definitions; that view is never
sent to the elapsed-time scheduler. There are not two editable duration sources.

`scheduling/work_method_time.py` owns `schedule_work_method_time(problem)` and
`validate_plan(problem, plan)`. It does not call the demonstration/control module.
The solver holds all authorised alternatives once and selects method, activity
mode, productive placement and necessary assignment together. Multiple solver
calls implement objective stages on one joint model; they are not separate
fixed-method candidate solves.

This is an explicit future-only composition profile, not an in-place upgrade to
accepted-progress workspace v2 or the older native elapsed-time project. The
portable input identifier is `pm-native-work-method-time/0`. Its `project`
contains the union of authorised activities, not an ordinary already-selected
workspace network. Do not send it to the current browser/workspace API.

No existing native files, hashes, approvals or histories are migrated. The old
elapsed scheduler and accepted-progress workspace paths are unchanged. The
public compatibility boundary is intentionally still provisional; this milestone
is not a final Engine v1 SDK or a claim that all native capabilities now compose.

## Bounded admission

The slice accepts at most 64 declared activities, 16 authorised structures, a
1..480 tick horizon and 20000 placement alternatives. Existing productive group
bounds and the 64 local assignment/set-combination bound remain in force.
Time uses the existing 30-minute coordinates and 48-tick daily calendars.

The existing native structural rules apply: unique method membership, one method
per package, every method activity feeds its completion, package predecessors
rather than cross-alternative activity arcs, and a controlling activity that is
always present. Every materialised graph is checked by the existing productive
validator so malformed inactive definitions cannot disappear behind selection.
Graph projection during admission performs no schedule solving.

Productive execution uses the existing joint-calendar placement compiler:

- every mandatory selected resource is available during execution;
- continuous work fits one complete joint interval;
- suspendable work pauses only at explicit calendar/availability gaps;
- resource occupancy covers productive periods, not their entire elapsed envelope;
- one person cannot fill two simultaneous slots;
- assignments remain consistent throughout the activity's productive periods;
- independent disjoint resource groups retain native quantities, not fake workers.

Named physical requirements are always assigned explicitly in this composition
path, including legacy RIGGER slots even when the source requests pooling. A
per-tick capacity relaxation cannot prove that one physical resource can remain
assigned across every productive segment of a suspendable activity. Genuine
identity-free capacity is represented by declared `resource_groups`; the compiler
chooses a consistent anonymous unit set across all productive segments. Group
capacity units never appear in public plan entries or public allocation witnesses.

A mode with no placement is disabled; if every method of a required package is
unavailable the result is infeasible within the declared horizon. Definitions are
not deleted or patched to obtain feasibility.

## Initial-plan policy and proof

There is no approved reference plan in this slice. Optimise sequentially:

1. controlling finish;
2. weighted start-time sum, using each activity's index in the full declared
   input as its weight and zero contribution for inactive activities;
3. declared method index, package by package;
4. declared mode index, activity by activity (inactive activity contributes zero);
5. deterministic placement ordering for the remaining representation ties.

Each proven optimum is fixed before the next stage. The authoritative path uses
no mixed-radix objective. A fixed-method comparator retains the original full-input start
weights; compressing indices after removing an inactive method would change the
comparison. The first two tiers and both declared choice vectors are compared.

Canonical stage ordering is a same-environment repeatability control, not a
cross-version/platform guarantee. Every CP-SAT stage has a deterministic-work
budget of 60.0 and the result records that budget together with solver version,
workers, seed and per-stage statuses. `UNKNOWN`, `FEASIBLE` without an optimum,
and `MODEL_INVALID` are not reported as project infeasibility or a successful
proven plan. The bounded entry point returns no authoritative plan for those
outcomes.

The input hash identifies the **complete portable input**, including reported-only
provenance. It is not the existing workspace trusted-state hash. Consequently a
reported-only change may change document identity without changing the schedule.
A plan hash is an integrity/identity check, not authentication or proof of optimality.

## Independent checks and controls

For the selected structure, the existing pattern-aware global allocator checks
whole-activity resource assignments and requires the allocation to explain each
suspension gap. Submitted named assignments are pinned, not silently repaired.
Its returned witness is additionally checked by the older exact physical checker.
Neither checker schedules the project or calls the candidate CP model. Group
quantities are checked through a complete existential allocation without exposing
anonymous workers. `validate_plan` checks input identity, method/mode coverage,
entry ownership, group quantities, objective accounting and physical feasibility.
It does not independently certify solver optimality metadata.

`native_work_method_time.py` owns the control, not the engine. It enumerates each
fixed-method/fixed-mode network and solves explicit assignment with a separately
constructed per-tick resource-capacity model. The candidate uses conditional
structure and optional productive occupancy intervals instead. Both reuse source
calendar interpretation and the established local placement construction: this
is not a completely independent implementation of all calendar mathematics.

A separate four-activity microcase exhaustively enumerates starts, finishes and
physical occupancy directly in Python, without either compiler, checker, calendar
helper or CP-SAT. It verifies the complete objective under normal availability
and a changed named-resource outage. This stronger oracle is bounded to that case.

## Executable scenario

Thirteen declared activities, four work packages and two authorised removal
methods: lift the complete component or remove it in segments. The lift has two
authorised activity modes; the shorter mode competes for a parallel specialist.
The scenario includes named mechanical/specialist/crane requirements, two units
of genuinely interchangeable rigging capacity, a lunch gap, a crane-only check
that can occupy that gap, and an uninterrupted quality check before handoff.

Compare normal conditions, a reported-only outage, and that outage after explicit
acceptance. The input structure/work/calendar definitions must stay unchanged.
The candidate must match every control's complete best policy, repeat exactly in
the same environment, select only authorised active work and survive native
save/reopen with independent validation and no scheduling call.

Run:

```bash
python -m unittest tests.test_work_method_time_integration -v
python -m deterministic_scheduling_core.native_work_method_time --output /tmp/work-method-time/results.json
```

The additive `Work-method productive-time` workflow runs those checks and retains
source SHA, test output, input scenarios, complete candidate plans, fixed controls,
per-stage proof statuses and measured costs. Existing POC smoke/browser checks
continue unchanged. Results are reported from the exact-head artifact; no result
is presumed solely because this contract or the implementation exists.

## Explicit exclusions and next boundary

No UI, hosting, invitations, accepted actuals, status advancement, approvals,
reference-plan stability, method changes on begun work, arbitrary preemption,
new elapsed/curing semantics, temporal relationship types, a generic workface
capacity model, soft deadlines, frozen-coordinate profile, aspiration policy or adaptive repair is
introduced. Unsupported productive-project fields continue to be rejected.

Later convergence work composed accepted history and rolling structural status.
The future-only Work-Method composition now also accepts `exclusion_groups` and
`latest_finish` with bounded hard semantics. This does not establish accepted-
history workface correctness. The faithful 160/120 projection now accepts both
fields, but still fails at the 64-activity admission guard; see
[the focused experiment](professional-workface-latest-finish.md).

Additive cost instrumentation reports compiler phases, base model size, proof
stages and post-solve validation outside persisted plan identity. PR #42's
experimental mixed-radix challenger matched the then-authoritative sequential
policy and reduced the 64/48 anchor from 138 to 11 calls. The subsequently adopted
`schedule_work_method_time(...)` now proves finish and global timing individually,
then exactly batches method/mode/placement digits. Historical sequential plans
remain valid without re-solving; see [adoption](authoritative-canonical-batching.md)
and [the historical cost decomposition](placement-canonical-cost-decomposition.md).

CP-SAT API/status references checked for this implementation:
https://developers.google.com/optimization/cp/cp_solver
https://or-tools.github.io/docs/pdoc/ortools/sat/python/cp_model
