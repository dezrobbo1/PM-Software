# Headless Resource Allocation Repair v0

## Question and scope

Can an identity-free pooled scheduling master use exact assignment feedback to
repair an unstaffable plan and reach the same complete declared objective as an
explicit-assignment reference?

This is a bounded executable experiment, not a permanent engine API, resource
schema, generic Benders implementation or replacement of the existing scheduler.
The base is merged PR #33 at `a4a70079a438f16ac66f29d4ce1a3b0b0d8cde19`.
The original resource-assignment experiment, checker and negative no-handover
fixture remain unchanged.

Run:

```bash
python -m deterministic_scheduling_core.resource_allocation_repair_experiment --output /tmp/resource-repair.json
python -m unittest tests.test_resource_allocation_repair_experiment -v
```

## Comparison frozen before execution

Use one source case per comparison, capacity-one physical resources, finite
30-minute tick horizons, explicit eligibility, the established continuous and
calendar-suspendable semantics, and the same objective in both approaches:

1. controlling handoff finish;
2. the existing declaration-order weighted start-time sum.

Identity is not an objective. A canonical serialization hash is measured across
repeat runs in the same solver version/configuration; it is not a claim of
cross-version or cross-platform uniqueness of every equally optimal schedule.

Three retained cases:

- **Overlap:** the existing 14-activity source case. Compare with B and retain C
  as a selective-assignment control. Do not call the hard-coded shared M1/M2
  diagnostic from the candidate loop.
- **Continuity:** a separate schedulable four-activity variant of the existing
  no-handover counterexample. A four-tick X can use M1 or M2; two-tick Y needs M1;
  two-tick Z needs M2 and cannot begin before tick 2. All work feeds DONE. The
  six-tick horizon permits repair; a four-tick variant tests actual infeasibility.
  Independent Python enumeration considers starts, completion and X's identity.
- **Calendar:** E has a [2,4) outage; L is unavailable [0,2). Four productive ticks
  of mechanical work can legitimately occupy [0,2),[4,6) with E even though the
  aggregate pool has availability throughout [0,6). L-only inspection and two
  interchangeable rigging jobs remain separate physical requirements.

## Placement-space admission

The old A compiler chooses productive periods from aggregate availability.
Those periods are not necessarily a superset of B's resource-dependent patterns.
Therefore simply adding cuts to that old A model would be an unfair comparison.

This candidate enumerates the existing B **local** placement possibilities and
projects away assignment identities, deduplicating (start, finish, productive
periods). It never reads a solved B reference, expected dates or manual staffing
repair. Every physically feasible B plan has an admitted projected pattern for
each activity. The master contains no activity-resource assignment variables.

This is existential projection, not identity-blind scheduling. Local assignment
combinations are still enumerated in preprocessing. Their count, projected
pattern count, preprocessing time and patterns missing from old A are reported.
All roster, qualifications, calendars and eligibility facts remain input costs.
No reduction in planner work or production scaling is claimed.

## Exact allocation boundary

The existing fixed-schedule checker is reused to cross-check returned witnesses.
A small independent pattern-aware allocator additionally checks that the witness
explains each suspension gap. Occupancy-only checking is insufficient: a resource
available during the supposed gap cannot justify a voluntary pause under this
profile, even if it is available during every submitted productive period.

The independent checker reconstructs permissible time from source calendars and
outages, checks complete coverage, productive totals, boundaries and precedence,
enumerates authorised per-activity assignments, and searches globally. One person
cannot occupy two simultaneous roles. Each activity's assignment stays unchanged
across its productive periods; suspension gaps consume no capacity.

It does not use CP-SAT, solved reference results or placement-compiler period
construction to establish the allocation proof. Both generator and checker still
share the source calendar slot interpretation. The tiny continuity enumeration
is the stronger independent end-to-end oracle for its own bounded case.

## Feedback and objective proof

Each iteration freshly minimises finish, fixes that iteration's proven finish,
then minimises timing. The next iteration discards those objective equalities.
A physically impossible pooled finish is allowed to increase after feedback.

After a proven assignment failure, deterministic deletion-based exact checks
reduce the conflicting activities. A reduction is adopted only when that
smaller fixed-pattern allocation problem is also PROVEN_INFEASIBLE. Otherwise
the previously proven core is retained. The no-good forbids exactly that
combination of activity patterns, not arbitrary dates, workers or priorities.

Why this is sound for the admitted finite problem: an executable whole-project
assignment would restrict to an executable assignment of each subset. Therefore
an unassignable subset of fixed patterns cannot occur in any executable plan.
The cut cannot remove an executable plan. Re-solving the projected relaxation
with these cuts provides a lower bound on the executable objective. When a
candidate attaining that bound also has a valid allocation witness, its complete
(finish, timing) objective is optimal for this admitted profile.

No universal performance/architecture theorem follows from this argument.
Conflict deletion is deterministic but is not a claimed minimum-cardinality
unsatisfiable-core algorithm. No-goods may require many iterations.

## Evidence/status rules

- Successful output requires proven master objective tiers and an exact physical
  witness. The evidence separates anonymous schedule patterns from that witness.
- An exhausted allocation search proves only the submitted pattern combination
  unassignable, not the whole project infeasible.
- Exhaustion of the finite master after sound cuts proves horizon-bounded
  infeasibility. It does not prove that an extended horizon is infeasible.
- A checker limit, unproved master optimum or iteration budget returns
  INCONCLUSIVE with no successful executable output and no invented optimum.
- A checker limit never justifies a cut. Inconclusive core reduction keeps the
  larger already-proven cut rather than promoting the attempted reduction.
- MODEL_INVALID raises an explicit modelling error rather than project
  infeasibility. No solver time limit is added in this bounded experiment.

Evidence JSON includes source cases/hashes, reference and candidate schedules,
physical witnesses, every candidate and cut, both objective components,
repeat-signature/trace results, source-data immutability, and actual costs.
Costs include all master builds/solves, checker calls/nodes (including conflict
reduction), local placement enumeration and total candidate elapsed time. The B
reference's end-to-end time includes its own normal checker. Runtime comparisons
remain small-case observations, not stable performance benchmarks.

## Observed result and protocol correction

The initial executable run at `d55a982` did NOT support an all-cases success
claim: the 14-activity overlap case exhausted the original 64-iteration budget.
The continuity and calendar cases reached allocation-verified optima matching B.
The limit, source cases, generator, allocation search, cuts and objectives were
not altered to force a positive result.

The initial reporting/tests incorrectly treated every unsuccessful hypothesis
comparison as failed evidence. That is corrected explicitly: CI checks evidence
integrity and expected bounded behaviour, while the report separately records
`INCONCLUSIVE_WITHIN_DECLARED_LIMITS`. It does not label this outcome
NOT_FALSIFIED. Contradictory infeasibility against a verified feasible B,
unverified successful output, changed source data or non-reproducible results
still produce EVIDENCE_FAILURE and an unsuccessful command exit.

An initial handwritten continuity timing expectation was also wrong. Independent
enumeration, not a changed solver or fixture, establishes the complete optimum
`(6,32)`: X starts at 2 using M1, Y uses M1 over [0,2), Z uses M2 over [2,4), and
DONE occurs at 6. The enumeration finds 11 feasible start/assignment/milestone
combinations at horizon 6 and none at horizon 4. Every emitted microcase cut is
checked against all enumerated feasible schedules. All 64 overlap cuts are also
rechecked as exact unassignable subsets in the focused tests.

See the exact-head CI JSON/console artifact for measured calls, nodes, timings,
patterns and cut sequences. A green check means the bounded experiment ran and
reported its limitations correctly, NOT that the pooled architecture won.

## Next integration decision

**Retain selective integrated assignment as the working baseline for the next
small Work-Method/productive-time convergence slice.** Keep genuinely
interchangeable capacity pooled and keep the physical checker independent.

This specific exact-pattern feedback implementation has not justified replacing
that baseline: it did not find a usable allocation for the existing 14-activity
case within its declared budget, while the existing B/C approaches did. The two
successful small cases establish that correct feedback and a later executable
finish are possible; they do not establish a sufficiently effective general
repair mechanism. Projection also still incurs local identity enumeration.

Do not increase the budget, add stronger general cuts or start another
resource-decomposition programme merely to rescue this hypothesis. Retain the
experiment as a comparison for a future *concrete* scaling need. This is not a
universal rejection of pooled scheduling with better decomposition.

The next task should compose existing Work-Method structure with productive
execution periods and the retained resource boundary, still headlessly and in a
small declared case. Accepted-history/rolling-status composition remains a
separate subsequent integration decision. No UI, hosting, invitations, public
model migration or objective-policy redesign is implied by this result.

## API references checked during implementation

Only the existing CP-SAT API/status semantics were checked externally; the
experiment and its proof argument above are project-specific.

- https://developers.google.com/optimization/cp/cp_solver
- https://or-tools.github.io/docs/pdoc/ortools/sat/python/cp_model
