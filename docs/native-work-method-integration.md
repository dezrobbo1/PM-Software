# Native Work–Method integration

This milestone moves one already-demonstrated scheduling concept into the owning
PM-Software native project model.

It does **not** invent a new planning hypothesis.  The bounded
`work_method_experiment.py` remains the control oracle.

## Native concepts

The solver-independent native model now has:

```text
Project
  ├─ fixed activities
  └─ WorkPackage
       ├─ authorised ExecutionMethod A
       │    └─ executable Activity primitives
       └─ authorised ExecutionMethod B
            └─ executable Activity primitives
```

An activity remains the executable primitive.  An `ExecutionMethod` is only a
finite authorised structural choice over declared activities; the engine may not
invent new activities, scope or methods.

A fixed activity network remains the special case where
`Project.work_packages == ()`.

## First bounded structural contract

For this slice:

- a structural activity belongs to exactly one execution method;
- a work package selects exactly one declared method;
- every activity declared by a method must feed that method's completion
  activity;
- method-internal activity precedence remains ordinary activity precedence;
- package-to-package structure is expressed with work-package predecessors;
- structural activities may also depend on always-active fixed activities;
- fixed activities cannot depend directly on optional structural activities;
- the objective activity may belong to a structural package only when that
  package has one method;
- a frozen structural activity forces its containing method.

These constraints are intentionally narrower than a general planning language.

## Scheduling

The normal `schedule_project(...)` path owns structural selection.

For every work package the model chooses one authorised method, activates only
that method's activities, and jointly reasons about:

- selected structure;
- activity execution mode;
- precedence;
- resource capacity;
- exclusion groups;
- timing.

Inactive method activities have no resource occupancy and are omitted from the
returned schedule.

`ScheduleResult.selected_methods` records the selected package/method pairs.

The existing fixed-network objective ordering remains:

1. controlling finish;
2. planned-start movement where such reference coordinates exist;
3. deterministic timing tie-break;
4. a final declared-method tie-break only when the higher-order result is
   otherwise equal.

This milestone does not adopt the separate aspiration/recovery-policy experiment.

## Persistence

Saved native project documents use `pm-native-project-v1` and include
`work_packages`.

The loader still accepts `pm-native-project-v0`; v0 projects reopen as the
unchanged fixed-network special case with no inferred work packages or methods.

This versioning applies to `project/model.py` native-project documents.  It is
separate from the planner-workspace v0/v1/v2 accepted-progress schemas.

## Executable oracle

The convergence experiment uses the same six-package case as
`work_method_experiment.py`.

The control enumerates all eight authorised fixed networks.  The candidate
holds the authorised methods once in the native model and calls the normal
native scheduler.

The required comparisons are:

| Scenario | Expected structural response |
| --- | --- |
| A — normal availability | SCAFFOLD / CRANE / NORMAL |
| B — crane outage | SCAFFOLD / SEGMENTED / NORMAL |
| C — earlier specialist + narrow scaffold access | ROPE / CRANE / SPECIALIST |

The convergence passes only if the native scheduler matches both the exhaustive
oracle's controlling finish and its selected method vector in all three
scenarios, and repeated native solving is canonical.

## Evidence boundary

This milestone proves only that the bounded Work–Method structure can live in
the owning native project/scheduler layer rather than in a separate experimental
solver.

It does not yet compose Work–Method choice with:

- productive/joint working-time calendars;
- planner-level resource groups;
- accepted execution history;
- rolling status advancement;
- aspiration-bounded recovery policy;
- adaptive semantic repair.

Those richer capabilities currently live in other proven paths and must be
converged deliberately rather than silently assumed to be integrated.
