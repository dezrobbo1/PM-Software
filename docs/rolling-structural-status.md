# Rolling Structural Status v0

## Question

Can a validated structural recovery become the active execution structure for the
next status cycle, while preserving accepted history exactly and preventing a
newly started recovery method from being optimised away later?

This milestone composes:

- the accepted-history + Work-Method recovery from PR #36;
- the existing atomic `advance_status_point(...)` transaction;
- the same Work-Method/productive-time scheduler and physical validation.

It does not introduce a new enterprise status schema, a generic baseline
framework, or a new recovery-approval state. Promotion consumes a validated
calculated recovery; separate approval semantics remain outside this slice.

## Structural handover

A one-status recovery may select a different authorised method for a package that
has no accepted execution. That recovery cannot be rolled forward by the old
fixed-network status workspace unchanged, because the selected activity set may
have changed.

`promote_structural_recovery_to_status_cycle(...)` performs one bounded
same-status handover:

1. require any pending reported execution assertions to be resolved first;
2. validate the structural recovery;
3. reuse its already-proved nested future plan as the next reference plan;
4. reuse the exact compiled future problem as that plan's reference source;
5. materialise the recovery's selected methods as the new active execution
   structure;
6. copy accepted records byte-for-byte for activities retained in that structure;
7. reject promotion if any accepted executed activity would disappear;
8. omit unexecuted activities from deselected alternatives;
9. create explicit accepted `NOT_STARTED` assertions, at the current status
   boundary, for newly selected activities;
10. retain lineage to the prior status-state hash, recovery-plan hash, prior
   reference-plan hash and promoted reference-plan hash.

Promotion does not call the solver and does not mutate the prior status workspace.

The portable `pm-native-rolling-structural-status/0` document stores the current
Work-Method input, narrowed reference source, reference plan, active status
workspace and promotion lineage. Save/reopen validation does not recalculate.

## Reference handover

The next cycle does not manufacture another initial Work-Method solve.

The structural recovery already contains a complete validated
`future_plan`. The compiler input against which that nested plan was proved is
reconstructed deterministically without solving and becomes the next
`reference_problem`.

A narrowed reference problem may contain only the already-selected method for a
package whose history has made that method hard. Current planning may still retain
other authorised alternatives. Validation therefore requires:

- the same work-package ID set;
- the prior selected method to remain authorised in the current package;
- the prior selected method's structural definition and package predecessors to
  remain unchanged.

Current reports and forecast facts remain separate from that historical
reference identity.

## T1 -> T2 -> T3 control

The control reuses PR #36's eight-activity fixture.

### T1 — structural recovery and promotion

Initial reference:

- `REMOVE=LIFT`;
- `RESTORE=CRANE`;
- finish tick 8.

Accepted T1 status at tick 4:

- PREP completed `[0,2)`;
- LIFT in progress with actual `[2,4)`;
- LIFT accepted remaining estimate = 8;
- REST_CRANE and DONE not started.

The validated recovery selects:

- `REMOVE=LIFT`;
- `RESTORE=MANUAL`;
- finish tick 12.

Promotion creates the next active structure:

- PREP;
- LIFT;
- REST_MAN1;
- REST_MAN2;
- DONE.

REST_CRANE is absent because it never executed. REST_MAN1 and REST_MAN2 receive
explicit accepted `NOT_STARTED` assertions at tick 4. PREP and LIFT accepted
records are copied unchanged.

### T2 — newly selected method begins

Advance atomically to tick 6:

- LIFT appends actual `[4,6)` and receives an independently reviewed remaining
  estimate of 2 ticks;
- REST_MAN1 starts at tick 4, executes `[4,6)`, and has 2 ticks remaining;
- REST_MAN2 and DONE remain not started.

Because REST_MAN1 now has accepted execution, `RESTORE=MANUAL` is hard.

Authoritative T2 recovery:

- `REMOVE=LIFT`;
- `RESTORE=MANUAL`;
- finish tick 12.

A deliberately illegal counterfactual removes only accepted method locks while
retaining the other status facts. It chooses:

- `REMOVE=LIFT`;
- `RESTORE=CRANE`;
- finish tick 10.

The shorter counterfactual demonstrates that the method lock is operationally
material, not merely a canonical tie-break.

### T3 — begun method completes

Advance atomically to tick 8:

- LIFT is completed with accepted actual periods
  `[2,4), [4,6), [6,8)`;
- REST_MAN1 is completed with accepted actual periods
  `[4,6), [6,8)`;
- REST_MAN2 remains not started;
- DONE remains not started.

Authoritative T3 recovery still keeps `RESTORE=MANUAL` and finishes at tick 12.

The same illegal no-lock counterfactual switches to `RESTORE=CRANE` and finishes
at tick 10. Completion therefore retains the structural lock just as in-progress
execution did.

Two structural promotion records are retained in lineage by T3.

## Validation

Run:

```bash
python -m unittest tests.test_rolling_structural_status -v
python -m deterministic_scheduling_core.rolling_structural_status_experiment \
  --output /tmp/rolling-structural-status/results.json
```

The focused workflow retains exact source SHA, test output, result document and
runtime metadata.

## Explicit boundary

This slice does not add:

- arbitrary method switching after execution begins;
- unplanned field execution of an alternative absent from the selected structure;
- positive-remainder continuous in-progress structural continuation;
- anonymous-group no-handover across the history/future boundary;
- changed historical execution-context segmentation;
- structural/temporal stability objective policy;
- browser workflow;
- generic baseline/scenario management;
- production-scale evidence.

If this slice survives review, the converged headless execution path is coherent
enough to justify a bounded larger-scale falsification case before expanding the
schema or UI.
