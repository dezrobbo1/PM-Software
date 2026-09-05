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

## Current research direction

The cumulative architectural hypothesis is now:

- executable resource/constraint-feasible schedules should be authoritative rather than CPM dates followed by post-hoc levelling;
- CPM/temporal analysis remains useful as an analytical service, not necessarily the authoritative scheduler;
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

High-value unresolved questions now include the analytical role of **CPM/float/criticality** after integrated resource/method scheduling, richer **calendar/state scheduling semantics** if real capability requires them, and later genuinely larger-scale performance/decomposition evidence. The exact lower-order objective hierarchy also remains open.

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
  tests.test_adaptive_repair_experiment -v
```

## Active repository map

- `src/deterministic_scheduling_core/project/` — current PM-Software-owned native activity project model and JSON persistence.
- `src/deterministic_scheduling_core/scheduling/` — current scheduler/optimiser consuming only the native model.
- `src/deterministic_scheduling_core/adapters/` — optional external-system translators.
- `src/deterministic_scheduling_core/work_method_experiment.py` — bounded structural-planning-choice experiment.
- `src/deterministic_scheduling_core/trusted_state_experiment.py` — field event → validation → trusted state → replan experiment.
- `src/deterministic_scheduling_core/objective_policy_experiment.py` — aspiration-bounded recovery experiment.
- `src/deterministic_scheduling_core/adaptive_repair_experiment.py` — full vs fixed-local vs adaptive-semantic replanning experiment.
- `src/deterministic_scheduling_core/prototype2_native.py` — first end-to-end native project workflow.
- `tests/` — focused reference and prototype tests.
- `docs/` and `docs/archive/` — current direction and historical research.
