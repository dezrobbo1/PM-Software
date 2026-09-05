# PM-Software — deterministic AI project-management research

**Status: exploratory R&D / proof of concept**

## Aim

This project investigates whether modern technology can enable a **new, better and leaner approach to professional project planning, scheduling and execution control**.

The original technical idea is a **deterministic AI core**: a trustworthy computational core that can reason about project logic, resources, operational constraints, alternatives and changing execution conditions, while modern AI can assist where it adds genuine value.

We are not trying to copy Primavera P6 or Microsoft Project. Existing products are useful sources of knowledge, comparison and future interchange, but they do not define our architecture, semantics or product model.

## Working loop

**Research → Idea → Prototype → Test → Learn → Next experiment**

Before substantial work, ask:

> **What will we be able to do, demonstrate or know after this that we cannot do or know now?**

Research, documentation, tests, refactoring, validation, compatibility work and hardening support the project. They are not progress by themselves.

## Cumulative evidence

New experiments refine the project; they do not erase earlier evidence unless they directly contradict it.

**Gate 1 through Gate 5 are provisionally demonstrated.**

- Gate 1: feasible resource-constrained scheduling and a better whole-project sequence than a fixed-priority baseline.
- Gate 2: context-sensitive execution-mode choice; the locally fastest activity mode is not always the best project decision.
- Gate 3: permit/access and workface constraints can turn a mathematically shorter resource-feasible plan into a non-executable one.
- Gate 4: a small execution disturbance can propagate through the plan while unaffected work is preserved and the cause remains explicit.
- Gate 5: an anonymised slice derived from a real shutdown schedule contained a declared resource overload; the core removed it while preserving the controlling handoff, and the experienced practitioner accepted the result.

These are proof-of-concept results, not production scheduling claims.

## Native product boundary

Prototype 1 proved that a real Microsoft Project XML schedule can expose a real planning problem to the experimental core. It also established the architectural boundary:

```text
Microsoft Project XML ─┐
P6/XER later           ├──> external adapters ──> PM-Software native project ──> native scheduler/core
manual/native input ───┘
```

External-system fields stop at adapter boundaries. The native project model and scheduling core must not depend on Microsoft Project, P6 or another scheduling package.

Prototype 2 then established that PM-Software can create, persist, reopen, edit and optimise its own native project without Microsoft Project or P6 in the workflow.

The current native model contains projects, activities/milestones, finish-to-start precedence, resources/capacity demand, alternative activity execution modes, not-before/latest-finish boundaries, workface-style exclusion groups, planned/frozen coordinates and a controlling objective activity. The scheduler consumes that native model only.

## Planning-model experiment — Work–Method–Execution

Targeted research challenged the assumption that a planner must completely select one activity network before the scheduling engine can reason about the project.

The bounded hypothesis is:

```text
required work / outcome
        ↓
finite authorised execution methods
        ↓
method-specific activities and activity modes
        ↓
integrated method + resource + sequence + timing decision
        ↓
explicit execution plan
```

Activities remain executable primitives. The engine may choose only among explicit authorised alternatives; it must not invent scope or arbitrary methods.

Run:

```bash
python -m deterministic_scheduling_core.work_method_experiment
```

The six-work-package case contains 33 possible activities and 8 authorised fixed-network structures. The integrated candidate matched exhaustive fixed-network enumeration in all three changed-condition scenarios:

| Scenario | Oracle | Integrated candidate | Selected structural choices |
|---|---:|---:|---|
| Normal | H37 | H37 | SCAFFOLD / CRANE / NORMAL |
| Crane unavailable H10–H18 | H41 | H41 | SCAFFOLD / SEGMENTED / NORMAL |
| Specialist earlier + scaffold limit H09 | H35 | H35 | ROPE / CRANE / SPECIALIST |

The bounded representation held 33 activity facts and 33 relationship facts once, compared with 180 activity facts and 176 relationship facts across the eight materialised networks.

**Result: not falsified.** The result supports bounded authorised structural choice; it does not justify unrestricted goal/state planning or make CP-SAT the product architecture.

## Execution-state experiment — Trusted Live Project State

Targeted research challenged direct field-to-schedule mutation.

The tested boundary is:

```text
field reality
    ↓
reported event + provenance
    ↓
validation / acceptance
    ↓
trusted project state
    ↓
unchanged deterministic scheduler
    ↓
executable plan
```

Run:

```bash
python -m deterministic_scheduling_core.trusted_state_experiment
```

The 20-activity experiment compared direct mutation with a bounded event/provenance + trusted-state projection.

Observed result:

- approved handover: 8h00m;
- direct mutation: 7 authoritative replans, 4 from unvalidated reports;
- 3 direct-mutation states were later corrected;
- those temporary states caused 22 moved starts / 48h15m aggregate start movement;
- trusted-state path: 4 provisional impact calculations, 4 authoritative replans, 0 from unvalidated reports;
- both paths reached the same final 11h30m handover after the same accepted facts were applied;
- validated actual history remained fixed;
- remaining duration remained a forecast assumption rather than historical fact;
- emergent repair activated only after explicit scope approval;
- reordered delivery of the same accepted events reproduced the same trusted-state and execution-plan hashes.

**Result: not falsified.** This supports a trusted live project-state boundary, not event-sourcing the whole application.

## Objective-policy experiment — Aspiration-Bounded Recovery

Targeted research then challenged the assumption that the mathematically earliest feasible finish should always define the authoritative recovery.

Run:

```bash
python -m deterministic_scheduling_core.objective_policy_experiment
```

The bounded policy stages are:

```text
protected commitment lateness
        ↓
controlling finish → F*
        ↓
Finish ≤ F* + Δfinish
        ↓
execution-method changes
        ↓
materially moved activity count
        ↓
absolute start movement
        ↓
canonical tie-break
```

The approved `SCAFFOLD / CRANE / NORMAL` plan finishes H37. A crane outage H11–H16 creates two recovery choices while H42 remains an achievable protected handoff.

| Policy | Selected recovery | Finish | Method changes | Moved starts | Start movement |
|---|---|---:|---:|---:|---:|
| `Δfinish = 0h` | SCAFFOLD / SEGMENTED / NORMAL | H41 | 1 | 11 | 44h |
| `Δfinish = 1h` | SCAFFOLD / CRANE / NORMAL | H42 | 0 | 14 | 70h |

Both matched exhaustive enumeration, every staged optimisation was proven `OPTIMAL`, and the repeated 1h solve returned the same canonical plan.

**Result: not falsified.** Explicit aspiration bounds can change the preferred recovery for inspectable reasons. The exact lower-order ordering is still provisional: in this fixture structural preservation produces more temporal movement, so the experiment does not prove structural stability should always outrank temporal stability.

## Replanning-propagation experiment — Adaptive Semantic Repair

The latest targeted research asked whether a local trusted-state change should cause full remaining-project optimisation, a permanently fixed local repair, or a local repair boundary that expands only through explicit project semantics.

Run:

```bash
python -m deterministic_scheduling_core.adaptive_repair_experiment
```

The bounded fixture contains:

- 12 work packages;
- 160 possible activities;
- 120 activities in the approved fixed plan;
- 4 flexible Work–Method packages / 16 authorised method combinations;
- pooled MECH/ELEC/QA resources;
- named crane `C04`;
- two workface exclusion groups;
- protected handoff H60.

A single trusted outage makes `C04` unavailable H38–H43. The local WP-04 crane activity `P04A07`, approved H38–H41, is displaced to H43–H46. That overlaps remote `P09A07`, approved H44–H47, even though WP-04 and WP-09 have no precedence relationship.

Three strategies were run against the same changed state and policy:

| Strategy | Result | Finish | WP-09 method | Free approved activities | Free method decisions | Solver calls |
|---|---|---:|---|---:|---:|---:|
| A — full remaining-project optimisation | feasible | H60 | SEGMENTED | 120 | 4 | 16 |
| B — fixed local repair | infeasible | — | fixed CRANE | 5 | 0 | 1 |
| C — adaptive semantic repair | feasible | H60 | SEGMENTED | 14 | 1 | 4 |

Full and adaptive produced the same policy vector: 1 method change, 4 materially moved activities, maximum 5h shift and 20h aggregate start movement.

Adaptive expansion was explicit and deterministic:

```text
N0
P04A07 shifts because C04 is unavailable
↓
P09A07 enters because its approved C04 occupancy overlaps the shifted interval
↓
N1
P09A08/P09A09/P09A10 enter because they are fixed precedence successors
↓
N2
complete WP-09 Work–Method decision enters because the approved crane method
cannot clear the protected H60 handover and an authorised no-crane method exists
↓
WP-09 = SEGMENTED
↓
H60 handover preserved
```

A repeated adaptive run returned the same canonical result.

**Result: not falsified.** In this bounded case, adaptive semantic repair found the same policy-consistent recovery as full optimisation while freeing 14 rather than 120 approved activities and 1 rather than 4 method decisions. The fixed local boundary could not recover.

This supports the following replanning hypothesis:

```text
trusted state change
        ↓
small semantic repair neighbourhood
        ↓
fix unaffected approved decisions
        ↓
optimise + validate globally
        ↓
expand only through explicit boundary causes
        ↓
full remaining-project optimisation only when locality effectively breaks down
```

Neighbourhood selection belongs above the solver. Initial expansion semantics should remain limited to concepts PM-Software already understands: precedence, pooled/named resources, workface/exclusion, Work–Method structure and protected commitments.

This is **not** a production decomposition algorithm, a general dependency framework, or evidence that 120 active activities represents professional-scale performance. Do not hard-code arbitrary percentage/radius thresholds from this experiment.

## Criticality-semantics experiment — Logic Float vs Executable Criticality

Targeted research then challenged whether traditional CPM float and critical-path labels can be treated as authoritative execution criticality once resources and authorised method alternatives are active.

Run:

```bash
python -m deterministic_scheduling_core.criticality_semantics_experiment
```

The experiment reuses the approved H60 structure from the adaptive-repair fixture. It computes a precedence-only CPM view of the selected structure, deliberately ignoring resources and method reselection, then perturbs the same activities through the integrated scheduler and existing recovery policy.

Two bounded counterexamples were demonstrated:

| Activity | Logic CPM | Resource/method-aware counterfactual |
|---|---|---|
| `P04A07` | 7h logic float | only 3h fixed-structure slack; +4h forces a remote `WP-09=SEGMENTED` method change to preserve H60 |
| `P09A07` | 0h logic float / logic-critical | +1h makes the approved crane structure infeasible, but authorised `SEGMENTED` method recovery still preserves H60 |

The first case shows that precedence-only float can overstate executable flexibility because a named-resource coupling becomes controlling before the logic float is exhausted. The second shows that zero logic float does not mean the project has no executable recovery: an authorised structural alternative can absorb the disturbance without moving the protected handoff.

A repeated adaptive counterfactual returned the same canonical result.

**Result: not falsified.** Traditional CPM remains useful for dependency analysis of one selected activity structure, but its float is not executable slack and its critical path is not the complete authoritative description of execution criticality when resource coupling and method choice are active.

Working terminology for follow-on experiments:

- **logic float / logic critical:** CPM properties of one selected precedence structure;
- **fixed-structure executable slack:** perturbation that can be absorbed while retaining the selected method structure under real resource/constraint rules;
- **counterfactual / policy criticality:** the consequence of a change when authorised recovery choices are allowed, expressed as an impact vector such as protected-commitment/finish effect, method reselection, schedule movement and causal constraint.

Do not force execution criticality into one continuous path merely to preserve conventional terminology. This is bounded synthetic evidence, not a production delay-analysis method or a settled permanent criticality schema.

## Working-time experiment — Productive Duration and Joint Availability

Targeted research then challenged the universal elapsed-time rule `finish = start + duration` for ordinary resource-consuming work.

Run:

```bash
python -m deterministic_scheduling_core.working_time_experiment
```

The 18-activity experiment used 30-minute resolution, day and selected night mechanical capability, named crane `C04`, inspection availability, a meal break, overnight non-working time, suspendable and continuous work, and finite authorised execution methods. It compared exactly three interpretations:

- **A — elapsed duration:** processing requirement becomes one continuous elapsed span;
- **B — productive/primary calendar:** work accumulates on the primary activity calendar but ignores other mandatory resource calendars;
- **C — productive/joint availability:** work accumulates only when the activity and every mandatory resource calendar are open, with capacity allocated separately.

Observed whole-project results:

| Interpretation | Project finish | Invalid activities | Non-working slots counted | Resource-calendar violations | Int / Bool vars | Optional intervals / candidate segments | Constraints |
|---|---|---:|---:|---:|---:|---:|---:|
| A | Day 5 17:00 | 15 | 46 | 50 | 36 / 5,521 | 4,863 / 5,184 | 15,945 |
| B | Day 5 17:30 | 3 | 0 | 4 | 36 / 2,563 | 2,565 / 2,886 | 7,731 |
| C | Day 6 10:00 | 0 | 0 | 0 | 36 / 2,478 | 2,481 / 2,802 | 7,477 |

The mandatory ten-productive-hour `MECH + C04` sentinel produced:

- A: Day 1 07:00 → Day 1 17:00;
- B: Day 1 07:00 → Day 1 17:30;
- C: Day 1 07:00 → Day 2 07:30, using only 07:00–12:00, 12:30–17:00 and Day 2 07:00–07:30.

The C compiler represented those three execution periods separately, so neither `MECH` nor `C04` was reserved across lunch or overnight. A five-hour continuous joint-resource activity was not split across the 12:00–12:30 break; it waited until one complete executable window was available.

A trusted `C04` outage at Day 1 10:00–14:00 preserved the accepted 07:00 start and three productive hours already completed. Remaining work was seven productive hours, executed 14:00–17:00 and Day 2 07:00–11:00. The four-hour outage added no processing work. Only an explicit one-hour rerig requirement raised remaining work to eight hours and moved forecast finish to Day 2 12:00.

The authorised method choice changed for an inspectable reason:

- normal joint calendars: `A15=CRANE`, Day 5 07:00–12:00;
- trusted Day 5 `C04` unavailability: `A15=SEGMENTED`, using `NIGHT_MECH` Day 5 18:00–Day 6 00:00.

A repeated C solve returned the same canonical plan signature.

**Result: not falsified.** A produced operationally impossible work, B corrected primary working-time counting but still missed mandatory-resource availability, and C produced a physically executable result. For this bounded case, the finite-placement CP-SAT compiler remained small enough to inspect and explain; the evidence does not yet justify a CP Optimizer challenger.

This result does not make calendars a settled permanent schema, prove production scale, justify unrestricted preemption, or establish cross-version/cross-platform reproducibility. Elapsed duration remains legitimate for genuinely clock-driven processes such as the fixture's cure activity.

## Current research direction

The cumulative architectural hypothesis is now:

- executable resource/constraint-feasible schedules should be authoritative rather than CPM dates followed by post-hoc levelling;
- CPM remains useful as a **logic-analysis service** over a selected precedence structure, with its output labelled logic float/logic criticality rather than executable slack;
- execution criticality should be tested counterfactually against resources, constraints, authorised method choices and project policy rather than inferred only from a precedence path;
- ordinary resource-consuming duration should provisionally represent productive processing placed into executable time, while genuinely clock-driven processes may retain elapsed-time semantics;
- suspendable work may cross explicit calendar or trusted-availability gaps without reserving resources through the gap; continuous work must fit one uninterrupted executable window;
- mandatory-resource calendar eligibility and resource-capacity allocation are separate constraints, and both must hold for productive execution;
- trusted actual productive work must remain distinct from forecast remaining productive work; availability loss alone does not create work;
- activities remain the language of execution;
- bounded work packages and finite authorised execution methods may become the language of planning choice;
- the scheduler may jointly choose authorised method, resource/mode, sequence and timing;
- the live object should be **trusted project state**, with schedules derived from accepted facts/assumptions rather than directly mutated by field reports;
- hard facts and genuinely non-negotiable conditions sit outside tradeable objective penalties;
- protected commitments and controlling completion can be followed by explicit aspiration bounds before lower-order stability concerns;
- structural and temporal disruption are distinct dimensions and their exact ordering remains open to evidence;
- routine replanning should provisionally preserve approved decisions and expand an optimisation neighbourhood through explicit causal constraints only when needed;
- full remaining-project optimisation remains an escalation and experimental quality benchmark;
- CP-SAT remains the primary experimental backend for now, but it is not the native architecture;
- human/project rules remain authoritative over required work, admissible methods, validation authority, constraints, protected commitments and objective policy.

Do not promote these hypotheses into large schemas or frameworks merely because bounded experiments worked.

High-value unresolved questions now include professional semantics of capability/resource substitution, later genuinely larger-scale performance/decomposition evidence, further evidence on the exact lower-order objective hierarchy, and richer irregular/calendar-state cases only when a focused capability requires them.

Do not substitute broad compatibility work, production hardening, a P6/MSP clone, full event sourcing, a generic objective-policy framework, a generic decomposition framework or a large UI framework for the next focused experiment.

## External-format adapter boundary

The bounded MSPDI adapter lives under:

```text
src/deterministic_scheduling_core/adapters/msproject_xml.py
```

It imports only the subset needed by the validated real decision-area experiment and translates that source into the native `Project` model. Do not expand compatibility merely because more external fields exist.

## Runnable experiments

```bash
python -m deterministic_scheduling_core run-gate1-experiment
python -m deterministic_scheduling_core.gate2_experiment
python -m deterministic_scheduling_core.gate3_experiment
python -m deterministic_scheduling_core.gate4_experiment
python -m deterministic_scheduling_core.gate5_experiment
python -m deterministic_scheduling_core.prototype1_workspace /path/to/project.xml
python -m deterministic_scheduling_core.prototype2_native /tmp/pm-native-project.json
python -m deterministic_scheduling_core.work_method_experiment
python -m deterministic_scheduling_core.trusted_state_experiment
python -m deterministic_scheduling_core.objective_policy_experiment
python -m deterministic_scheduling_core.adaptive_repair_experiment
python -m deterministic_scheduling_core.criticality_semantics_experiment
python -m deterministic_scheduling_core.working_time_experiment
```

## Parallel STO research

`dezrobbo1/STO-Scheduler-Tracker-Research` remains a separate STO-focused scheduling and live-execution experiment. It is not subordinate to PM-Software. Reuse useful ideas/tests/code deliberately; merge only if experiments later show that doing so simplifies development or improves the product.

## Existing research and history

Earlier Phase 0 material, schemas, registers, semantic work and native-validation work remain research references. They are not current acceptance criteria.

The large historical Microsoft Project machinery under `native/`, `native-validation/` and archived documentation is not an active architecture foundation. Do not extend it unless a future experiment explicitly reopens that research.

## Development setup

Python 3.11 or later is required.

```bash
python -m pip install -e .
python -m unittest \
  tests.phase1.unit.test_canonical_json_and_calendars \
  tests.phase1.unit.test_kernel \
  tests.phase1.unit.test_independent_validator \
  tests.test_gate1_experiment \
  tests.test_gate2_experiment \
  tests.test_gate3_experiment \
  tests.test_gate4_experiment \
  tests.test_gate5_experiment \
  tests.test_prototype1_workspace \
  tests.test_native_project_core \
  tests.test_work_method_experiment \
  tests.test_trusted_state_experiment \
  tests.test_objective_policy_experiment \
  tests.test_adaptive_repair_experiment \
  tests.test_criticality_semantics_experiment \
  tests.test_working_time_experiment -v
```

## Active repository map

- `src/deterministic_scheduling_core/project/` — current PM-Software-owned native activity project model and JSON persistence.
- `src/deterministic_scheduling_core/scheduling/` — current scheduler/optimiser consuming only the native model.
- `src/deterministic_scheduling_core/adapters/` — optional external-system translators.
- `src/deterministic_scheduling_core/work_method_experiment.py` — bounded structural-planning-choice experiment.
- `src/deterministic_scheduling_core/trusted_state_experiment.py` — field event → validation → trusted state → replan experiment.
- `src/deterministic_scheduling_core/objective_policy_experiment.py` — aspiration-bounded recovery experiment.
- `src/deterministic_scheduling_core/adaptive_repair_experiment.py` — full vs fixed-local vs adaptive-semantic replanning experiment.
- `src/deterministic_scheduling_core/criticality_semantics_experiment.py` — logic-CPM vs executable-criticality falsification experiment.
- `src/deterministic_scheduling_core/working_time_experiment.py` — elapsed vs productive/joint-calendar falsification experiment.
- `src/deterministic_scheduling_core/prototype2_native.py` — first end-to-end native project workflow.
- `tests/` — focused reference and prototype tests.
- `docs/` and `docs/archive/` — current direction and historical research.
