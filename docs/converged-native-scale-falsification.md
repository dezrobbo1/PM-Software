# Converged Native Scale Falsification v0

## Question

Can the converged native scheduling path preserve the correctness properties
already demonstrated on small fixtures when the declared planning problem is
materially larger?

This is a falsification experiment, not a generic benchmark suite and not
production-scale certification.

The case deliberately crosses the previous Work-Method/productive-time admission
boundary of 32 declared activities while retaining a bounded structural oracle.

## Fixture

The retained case contains:

- **64 declared activities**;
- **48 active activities** in the baseline selected structure;
- **8 Work Packages**;
- **4 flexible Work Packages**;
- exactly **16 authorised structural combinations**;
- two activities with alternate execution modes, yielding **64 fixed
  method/mode control branches**;
- productive SHIFT and ALWAYS calendars;
- named resources `M1`, `I1` and scarce crane `C04`;
- disjoint interchangeable `MECH_POOL` and `RIGGING` resource groups;
- one controlling handoff activity `DONE`;
- accepted completed and in-progress execution;
- a trusted crane outage;
- structural recovery;
- promotion into the next active structure;
- one later status advancement.

The composition admission ceiling is raised from 32 to **64 declared
activities** for this evidence slice. A 65th declared activity is still rejected.
The existing limits of 16 authorised structures, 20,000 placement alternatives
and 480 horizon ticks are unchanged.

## Phase 1 — baseline joint planning

Without the crane outage, the joint candidate selects the STANDARD method for all
four flexible Work Packages:

```text
WP-02 = STANDARD
WP-04 = STANDARD
WP-06 = STANDARD
WP-07 = STANDARD
```

The controlling finish is tick **19**.

The candidate is compared with the existing separately constructed fixed-network
control. The control enumerates all 16 structural combinations and both alternate
mode decisions: **64 fixed method/mode networks**.

Candidate and control agree on the complete policy key.

Observed candidate model:

- 5,626 placement alternatives;
- 5,832 variables;
- 3,998 constraints;
- 138 lexicographic solver stages;
- about 0.13 s model build;
- about 14.00 s solver time;
- about 14.15 s end-to-end.

Observed fixed-control enumeration took about **35.24 s**.

These are CI observations from one synthetic case, not production performance
benchmarks.

## Phase 2 — accepted-history structural recovery

At status tick 8:

- `P01A01` is accepted completed;
- `P02A01` is accepted in progress under `WP-02=STANDARD`;
- `P03A01` is accepted in progress;
- the remaining selected activities are explicitly not started;
- crane `C04` has an accepted outage from tick 8 to 18.

The accepted-history recovery must preserve the begun WP-02 structural method.

It produces:

```text
WP-02 = STANDARD   # hard because execution has begun
WP-04 = STANDARD
WP-06 = STANDARD
WP-07 = ALTERNATIVE
finish = 22
```

The untouched WP-07 package changes method because its STANDARD method depends on
the unavailable crane.

Observed recovery model:

- 4,620 placement alternatives;
- 4,813 variables;
- 3,298 constraints;
- 130 solver calls/stages;
- about 14.76 s end-to-end.

The accepted status workspace is unchanged by calculation, and the repeated
calculation returns the same plan.

## Phase 3 — promotion and rolling status

The T1 recovery is promoted into the next active execution structure using the
rolling structural-status capability.

At T2, tick 18:

- the previously begun WP-02 and WP-03 roots are completed;
- the newly selected `P07B01` has begun;
- `WP-07=ALTERNATIVE` is therefore accepted structural history.

Authoritative T2 recovery produces:

```text
WP-02 = STANDARD
WP-04 = STANDARD
WP-06 = ALTERNATIVE
WP-07 = ALTERNATIVE
finish = 34
```

WP-06 remains untouched and is therefore still structurally free.

A deliberately illegal counterfactual removes accepted method locks while
retaining the other current facts. It selects:

```text
WP-06 = STANDARD
WP-07 = STANDARD
finish = 33
```

The counterfactual is shorter, but it erases the accepted execution of the
WP-07 alternative and is therefore not authoritative.

Observed T2 recovery model:

- 3,452 placement alternatives;
- 3,626 variables;
- 2,427 constraints;
- 118 solver calls/stages;
- about 7.76 s end-to-end.

This is direct evidence that history constraints remain operationally material at
the larger fixture size.

## Persistence and deterministic evidence

The experiment also proves:

- baseline plan validation after reopen without any solver call;
- rolling-cycle document reopen/validation without any solver call;
- same-environment repeated baseline, T1 and T2 calculations return the same
  plans;
- the original reference input hash is unchanged;
- independent physical validation remains mandatory.

Focused exact-source evidence is produced by:

```bash
python -m unittest tests.test_converged_scale_experiment -v
python -m deterministic_scheduling_core.converged_scale_experiment \
  --output /tmp/converged-native-scale/results.json
```

## Result

**The 64-declared / 48-active converged native case did not falsify the current
architecture.**

The previous 32-activity admission limit was therefore an experiment boundary,
not an observed correctness or solver boundary on this case. The retained
evidence supports moving that bounded ceiling to 64 while keeping 65+ outside
the admitted profile.

The result does expose a material scaling signal: the baseline candidate requires
138 sequential lexicographic solver stages and approximately 14 seconds in CI.
The fixed-network oracle takes approximately 35 seconds. That is acceptable for
this falsification slice but is not evidence that the current canonicalisation
strategy is suitable for professional-scale scheduling.

## Explicit boundary

This experiment does **not** establish:

- production-scale performance;
- acceptable interactive latency;
- a generic benchmark result;
- that 160 possible / 120 active activities will fit the current compiler;
- that the 20,000 placement cap is sufficient generally;
- that 138+ sequential lexicographic solves are the long-term objective
  implementation;
- browser workflow support for the converged structural-status model;
- continuous begun structural continuation;
- anonymous-group identity across the history/future boundary.

The next scale challenge should reuse the earlier professional-shaped
**160 possible / 120 active** fixture concepts against the converged native path.
If that case fails, classify the failure before changing architecture:
admission, placement generation, canonicalisation stages, CP-SAT proof budget,
independent allocation or scheduling semantics.
