# PM-Software working mode

This repository is exploratory R&D around the **deterministic AI core** idea. Read the root `README.md` before substantial work; it defines the current mission, cumulative evidence and active hypotheses.

## Default working loop

**Research → Idea → Prototype → Test → Learn → Next experiment**

Before substantial work, ask:

> **What will we be able to do, demonstrate or know after this that we cannot do or know now?**

If the answer is unclear, reconsider the work.

New evidence is cumulative. A later targeted report or experiment supersedes an earlier result only where it directly tests and contradicts that result. Do not restart already demonstrated work without a concrete reason.

## Capability first

For proof-of-concept development:

- implement the main path first;
- use the smallest experiment that can answer the current question;
- add focused tests for behaviour needed to trust that experiment;
- accept explicit limitations;
- reuse useful existing code;
- refactor only when existing code obstructs useful progress;
- stop once the current experiment has taught enough to move on.

A newly discovered issue is not automatically the next task. Fix it now only if it makes the current result materially wrong/unusable, creates a realistic destructive or security risk, or blocks the next useful experiment.

Do not let `review → fix everything → harden → rereview` replace capability development.

POC code may be temporary. Narrow fixtures, duplicated experimental paths and hard-coded research cases are acceptable when they are understandable and directly answer the question under test. Do not generalise merely because production software eventually might need a framework.

## Automated review policy

Automated review, including Codex review, is advisory during POC development.

Fix a finding immediately only when it makes the experiment materially wrong, unusable, destructive, realistically insecure or blocks the next experiment. One automated review attempt per meaningful capability change is normally enough. Do not manually retrigger a review merely because an automated reviewer hit a usage limit.

## Product direction

We are not reproducing Primavera P6 or Microsoft Project. They may be comparators, idea sources or future interoperability endpoints; they do not define PM-Software's semantics or architecture.

Do not assume CP-SAT, CPM, a particular AI model, MSPDI or the historical canonical schema is the final architecture. These are tools, adapters and experiments until evidence says otherwise.

The current product question is closer to:

> Given the trusted project state, resources, constraints, authorised methods and objectives, what is the best executable plan, and why?

## Native-model boundary — active rule

The dependency direction is:

```text
external source -> adapter -> PM-Software native project model -> scheduler/core -> workspace
```

Active rules:

- `project/` owns PM-Software native concepts;
- `scheduling/` consumes the native model only;
- `adapters/` translate external formats;
- external product fields/types must not leak into scheduling merely for compatibility;
- do not add MSP/P6 concepts to the native model merely because they exist externally;
- native projects must remain creatable, persistable, editable and schedulable without MSPDI/MPP/XER.

## Current scheduling hypotheses

Treat all of the following as evidence-backed hypotheses, not finished architecture.

### Integrated resource/constraint scheduling

Executable resource/constraint-feasible scheduling is the current authoritative planning hypothesis. CPM remains potentially useful as an analytical layer; do not automatically return to CPM dates followed by post-hoc levelling.

### Work–Method–Execution

The bounded experiment matched exhaustive enumeration of all 8 authorised fixed networks across three changed-condition scenarios while holding the alternatives once and selecting method + mode + timing jointly.

Active rules:

- activities remain executable primitives;
- a work package/outcome may have finite authorised methods where a real choice exists;
- the core may select only authorised methods/modes/resources/sequence/timing;
- it must not invent scope or arbitrary methods;
- fixed activity networks remain a valid special case;
- do not introduce unrestricted HTN/PDDL/state planning;
- do not promote `work_method_experiment.py` wholesale into the permanent model merely because the bounded case passed.

### Trusted live project state

The 20-activity experiment showed that unvalidated field reports can remain useful for provisional impact analysis without repeatedly contaminating the authoritative forecast. After the same facts were accepted, direct mutation and trusted-state projection reached the same final plan, while the trusted path performed zero authoritative replans from unvalidated reports.

Active rules:

- the live object is project state, not a schedule database receiving raw field edits;
- unvalidated reports may drive provisional analysis but must not silently become authoritative schedule truth;
- distinguish historical actuals, current operational facts, forecast assumptions and future planning decisions;
- validated history cannot be optimised away, but may be corrected through explicit superseding information;
- do not infer approved emergent scope merely from an inspection finding;
- preserve occurrence time separately from receipt time when late/out-of-order reporting matters;
- do not event-source the whole application merely because provenance is useful;
- do not promote the experiment's field-event classes wholesale into the permanent model.

### Aspiration-bounded objective policy

The bounded recovery experiment showed that explicit completion tolerance can change the selected plan for inspectable reasons:

- `Δfinish = 0h`: fastest H41 recovery, 1 method change;
- `Δfinish = 1h`: H42 recovery, 0 method changes;
- both matched exhaustive enumeration;
- repeated solving produced the same canonical result.

Active rules:

- actual history, frozen decisions, hard physical/logical constraints and genuinely non-negotiable gates are constraints, not tradeable objective penalties;
- establish the best controlling finish before applying any allowed degradation;
- express degradation explicitly as policy, not hidden giant weights;
- structural disruption and temporal movement are different dimensions;
- the exact lower-order ordering remains provisional;
- do not promote a permanent generic `PlanningPolicy` or broad multi-objective framework yet.

### Adaptive semantic repair

The latest bounded experiment tested how far replanning should propagate after one trusted disturbance.

Fixture:

- 12 work packages;
- 160 possible / 120 approved active activities;
- 4 flexible Work–Method decisions / 16 authorised combinations;
- pooled resources, named crane `C04`, workface exclusions and protected H60 handoff;
- a local WP-04 crane outage created a remote resource-only interaction with WP-09, with no WP4↔WP9 precedence link.

Observed comparison:

- **full optimisation:** H60, WP-09 `SEGMENTED`, 120 approved activities free, 4 method decisions free, 16 solver calls;
- **fixed local:** 5 activities free, no method choice, globally infeasible;
- **adaptive semantic repair:** H60, same method choice and same policy vector as full, 14 approved activities free, 1 method decision free, 4 solver calls;
- repeated adaptive repair returned the same canonical result.

The adaptive boundary expanded only through explicit native semantics:

```text
local C04 outage
↓
remote C04 overlap
↓
fixed precedence successors
↓
complete remote Work-Method decision
↓
protected handoff recovered
```

The **adaptive semantic repair hypothesis was not falsified** by this bounded experiment.

Active rules for follow-on work:

- preserve the approved plan by default;
- seed a repair neighbourhood from the trusted state change;
- initial/expansion semantics should use concepts we already understand: precedence, pooled/named resources, workface/exclusion, Work–Method structure and protected commitments;
- keep unaffected approved decisions fixed initially;
- every candidate repair must still be validated against the whole project;
- expand only when an explicit boundary cause requires more freedom;
- log the causal reason for each expansion;
- full remaining-project optimisation remains available as escalation and as an experimental quality benchmark;
- neighbourhood selection belongs above the solver; CP-SAT must not silently define which project decisions matter;
- do not introduce a generic decomposition framework, arbitrary graph-distance rule, arbitrary time radius or magic percentage threshold from this one experiment;
- this 120-active-activity fixture is not evidence of production-scale performance.

The experiment is deliberately isolated in `src/deterministic_scheduling_core/adaptive_repair_experiment.py`.

## Current position

Gate 1 through Gate 5 are provisionally demonstrated.

Prototype 1 established the bounded external-file bridge and native boundary. Prototype 2 established a standalone native project workflow.

The following bounded hypotheses have now survived their first executable falsification tests:

- integrated resource/constraint scheduling;
- context-sensitive execution modes;
- operational constraints;
- stable change propagation;
- Work–Method–Execution structural choice;
- trusted live project state;
- aspiration-bounded objective policy;
- adaptive semantic repair.

CP-SAT remains the primary experimental backend for now, but the project/domain model must remain solver-independent. Classical CP is a future challenger only if richer calendar/state semantics demonstrate a material capability advantage.

The next work should continue to attack one unresolved core question at a time. Strong candidates now are:

- **CPM/criticality semantics:** what CPM, float and criticality should mean when executable resource/constraint/method scheduling is authoritative;
- **calendar/state semantics:** only if a real capability requires richer working-time or state-transition modelling;
- **larger-scale evidence:** only after a focused question is defined; do not launch a generic benchmarking/hardening programme;
- **objective ordering:** gather further evidence before declaring structural-vs-temporal stability universally settled.

Do not default to UI, broad compatibility, production hardening, full event sourcing, generic objective frameworks or generic decomposition architecture in place of those focused experiments.

## Historical Microsoft Project machinery

Unless a new experiment explicitly needs it, do not extend the historical `native/msproject`, `native-validation`, protocol, register, manifest or compatibility machinery. It remains research history and source material, not the active architecture.

`prototype1_workspace.py` is a completed bounded bridge. Do not turn it into a general Microsoft Project importer simply because more MSPDI fields exist.
