# PM-Software — deterministic AI project-management research

**Status: exploratory R&D / proof of concept**

## Aim

This project investigates whether modern technology can enable a **new, better and leaner approach to professional project planning, scheduling and execution control**.

The original technical idea is a **deterministic AI core**: a trustworthy computational core that can reason about project logic, resources, operational constraints, alternatives and changing execution conditions, while modern AI can assist where it adds genuine value.

We are not trying to copy Primavera P6 or Microsoft Project. Existing products are useful sources of knowledge, comparison and potentially future interoperability, but they do not define our architecture or product model.

No final product architecture is assumed. Optimisation, constraint programming, AI, conventional scheduling mathematics, new data models and other approaches may all be researched and tested where useful.

## Working loop

**Research → Idea → Prototype → Test → Learn → Next experiment**

Research and ideas are valuable when they lead toward something testable. A failed experiment is useful progress when it tells us an approach does not work or what to try next.

### Forward Progress Principle

Everything we do should either increase working capability, test a promising idea, answer an important question that changes what we build next, or remove a real blocker to one of those things.

Before substantial work, ask:

> **What will we be able to do, demonstrate or know after this that we cannot do or know now?**

Research, documentation, tests, refactoring, validation, compatibility work and hardening support the project. They are not progress by themselves.

## Progress gates

These gates measure capability and useful learning, not process completion.

### Gate 1 — Core works

Can the deterministic AI core create a useful schedule?

### Gate 2 — Core adds value

Can it make a useful whole-project decision that a simpler local approach misses or handles less effectively?

### Gate 3 — Operational reality

Can meaningful real-world restrictions such as scarce resources, workfaces, access or permit windows be represented without impractical modelling overhead?

### Gate 4 — Change and replanning

Can the core respond sensibly when execution changes the plan, preserving unaffected work where possible and explaining important consequences?

### Gate 5 — Real-world proof

Does the approach remain useful outside synthetic examples?

Gate 5 passes only when representative real or anonymised project information has been tested **and an experienced practitioner judges the result useful enough to continue development**.

### Later — Productisation

Production hardening, comprehensive security, broad compatibility, deployment, large-scale performance guarantees and exhaustive validation belong later, if the experiments justify building a product.

## Current position

**Gate 1 through Gate 4 are provisionally demonstrated by working experiments. Gate 5 now has a successful technical trial but remains pending practitioner judgement.**

### Gate 1

```bash
python -m deterministic_scheduling_core run-gate1-experiment
```

An 18-activity resource-constrained sample produces a 48-hour fixed-priority baseline and a 38-hour CP-SAT schedule. The core advances the long branch so non-resource work can overlap other work, reducing makespan by 10 hours without breaking precedence or double-booking constrained resources.

### Gate 2

```bash
python -m deterministic_scheduling_core.gate2_experiment
```

The same repair can use a locally faster specialist-assisted mode or a slower normal mode. In one context acceleration is correct. In another, the optimiser deliberately selects the slower activity mode because preserving the scarce specialist lets the whole project finish three hours earlier.

### Gate 3

```bash
python -m deterministic_scheduling_core.gate3_experiment
```

A 16-hour resource-feasible optimum becomes non-executable when an access/permit window and workface exclusion are considered. Adding only those two operational facts produces a sensible executable 17-hour plan.

### Gate 4

```bash
python -m deterministic_scheduling_core.gate4_experiment
```

A one-hour named-crane outage is introduced after execution has started. The core moves the directly affected lift and its downstream chain by one hour, preserves unrelated future work, and explains the direct and propagated consequences.

### Gate 5 technical trial

```bash
python -m deterministic_scheduling_core.gate5_experiment
```

The Gate 5 fixture is an **anonymised 19-node derivative of a real shutdown schedule slice**. The raw Microsoft Project XML and identifying task/resource names are not committed to this public repository.

The source starts are treated as not-before boundaries so calendar and external-readiness facts that are outside the bounded slice are not silently pulled earlier.

The published slice contains a declared resource-capacity overload:

- `RES-B`: demand 3 against capacity 2 from M240 to M360.

The stable revision removes that overload while preserving the existing handoff at M600. Only two activities move:

- `R12`: M240 → M420 (+180 minutes);
- `R11`: M480 → M540 (+60 minutes).

Total later-start movement is 240 minutes. All other source coordinates remain unchanged, precedence is respected, and the handoff does not move.

This demonstrates that the core can process a bounded piece of less-curated real schedule structure and produce a technically feasible revision. **It does not by itself pass Gate 5.** The proposed movement still requires practitioner judgement about whether it makes operational sense.

## Gate 5 decision point

The next step is not another synthetic experiment or another hardening cycle.

An experienced practitioner should review the two proposed real-world movements in their original operational context and decide whether the result is sensible enough to continue.

If the result is sensible, Gate 5 can be provisionally passed and the next development phase should be chosen from what we learned rather than automatically starting production hardening.

If the result is not sensible, that is useful evidence: identify the missing operational fact, add the smallest representation needed for it, and rerun the real-world experiment.

## Parallel STO research

`dezrobbo1/STO-Scheduler-Tracker-Research` remains a separate STO-focused scheduling and live-execution experiment. It is not subordinate to this repository and should continue productive work in its own direction.

The two projects should compare results and selectively reuse useful ideas, tests or code. A future shared core, package or repository merge should be considered only when working experiments show that it would simplify development or improve the product.

## Existing research and history

Earlier Phase 0 material, schemas, registers, semantic work and native-validation work remain available as research references. They are not current acceptance criteria.

See `docs/README.md` and `docs/archive/`.

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
  tests.test_gate5_experiment -v
python -m deterministic_scheduling_core run-gate1-experiment
python -m deterministic_scheduling_core.gate2_experiment
python -m deterministic_scheduling_core.gate3_experiment
python -m deterministic_scheduling_core.gate4_experiment
python -m deterministic_scheduling_core.gate5_experiment
```

## Repository map

- `src/deterministic_scheduling_core/` — current reusable calculation and experimental code.
- `benchmarks/semantic/` — existing small semantic cases.
- `tests/` — focused reference and experiment tests.
- `docs/` — current and historical research documentation.
- `native-validation/` — paused Microsoft Project/P6 research material.
- `registers/` — historical evidence templates, not active development requirements.
- `docs/archive/` — superseded protocol snapshots, CI workflows, governance profile and manifest.
