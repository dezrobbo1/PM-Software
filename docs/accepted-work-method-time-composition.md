# Accepted History + Work-Method Composition v0

## Question

Can PM-Software preserve accepted execution history as non-optimisable fact while
still allowing untouched future work packages to choose a different authorised
execution method?

This is a bounded convergence experiment. It composes two already demonstrated
capabilities:

- accepted-progress v2 history and explicit remaining productive work;
- the future-only Work-Method/productive-time structural scheduler.

It does not introduce a new general status schema, event store, rolling structural
workflow or objective-policy framework.

## Input boundary

The experiment keeps three inputs separate:

1. a `WorkMethodTimeProject` containing the full union of authorised methods;
2. a previously calculated Work-Method plan identifying the reference selected
   structure;
3. an accepted-progress v2 workspace containing status only for that reference
   selected execution structure.

Inactive alternative activities do **not** receive fabricated `NOT_STARTED`
status records. Status belongs to the selected execution structure, while the
authorised union remains a planning definition.

The status workspace must still be the exact native projection of the reference
selected structure and share the same current report state.

## History-to-future compilation

`schedule_accepted_work_method_time(...)` first validates accepted history using
the existing v2 validator. It then compiles history into hard future-planning
constraints:

- a package becomes structurally fixed once any activity in its selected method
  has accepted `IN_PROGRESS` or `COMPLETED` history;
- completed activities become zero-work historical timing anchors at their
  accepted finish and consume no future resource capacity;
- in-progress activities keep the accepted mode and named resource identities;
- their future `processing_ticks` come from the separately accepted remaining
  estimate, not from original work minus actual work;
- every future activity is bounded at or after the status point;
- packages with no accepted execution retain every authorised method and may
  change structure.

After that compilation, the existing joint Work-Method/productive-time scheduler
still chooses the remaining method, mode, physical assignment and timing in one
future model.

This first slice explicitly rejects positive-remainder continuous in-progress
work. Its exact continuation semantics are already known in the fixed-network v2
path but are not composed with structural choice here.

## Executable falsification case

The eight-activity control contains:

- completed preparation;
- a removal package with `LIFT` and `SEGMENTED` methods;
- a restore package with `CRANE` and `MANUAL` methods;
- final handoff.

The initial plan selects:

- `REMOVE=LIFT`;
- `RESTORE=CRANE`;
- finish tick 8.

At status tick 4:

- preparation is completed at tick 2;
- `LIFT` has accepted actual productive work `[2,4)`;
- `LIFT` remains in progress;
- its accepted remaining estimate is revised to **8 ticks**, even though its
  original total processing estimate was 4;
- the restore package has not started.

The authoritative structural recovery must keep `REMOVE=LIFT`, because that
method has already begun. It may change the untouched restore package.

The expected bounded result is:

- `REMOVE=LIFT` remains fixed;
- `RESTORE` changes from `CRANE` to `MANUAL`;
- accepted LIFT history stays `[2,4)`;
- eight forecast productive ticks remain for LIFT;
- controlling finish becomes tick 12.

A deliberately illegal counterfactual removes only the begun-method lock. It
selects `REMOVE=SEGMENTED`, keeps `RESTORE=CRANE`, and reaches tick 11. That
shorter result is evidence for the semantic boundary: an optimiser can improve
the forecast by erasing reality unless accepted structural history is a hard
constraint.

## Independent control

The control does not use structural choice inside the candidate compiler. It
enumerates only method combinations permitted by accepted history, materialises
each fixed network, recreates the same accepted execution facts, and runs the
existing accepted-progress v2 scheduler on each network.

The candidate must match the control on:

- permitted selected methods;
- controlling finish;
- physical feasibility.

This control shares the existing productive/status scheduling implementation; it
is a structural-composition control, not a fully independent scheduling-math
implementation.

## Validation and persistence

The composed plan stores:

- original Work-Method input hash;
- accepted v2 state hash;
- reference plan hash;
- fixed method map;
- selected methods/modes;
- actual and forecast fields side by side;
- the complete validated future-plan proof;
- a plan integrity hash.

Reopening the Work-Method input, status workspace, reference plan and composed
plan performs validation without calling the scheduler.

Run:

```bash
python -m unittest tests.test_accepted_work_method_time -v
python -m deterministic_scheduling_core.accepted_work_method_time_experiment \
  --output /tmp/accepted-work-method-time/results.json
```

## Explicit boundary

This milestone proves one status point only.

It does not yet add:

- T1 -> T2 -> T3 structural status advancement;
- method switching after a package has begun;
- unplanned field execution of an alternative method that was absent from the
  reference selected structure;
- continuous in-progress structural continuation;
- approved-plan structural/temporal stability objectives;
- arbitrary preemption;
- browser workflow;
- production-scale evidence.

If this experiment survives review, the next focused question is whether the same
method-lock/history semantics remain correct across repeated rolling status
advancement.
