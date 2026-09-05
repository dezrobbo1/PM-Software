# PM-Software working mode

This repository is an exploratory R&D project built around the **deterministic AI core** idea. Read the root `README.md` before substantial work; it defines the current mission and active experiments.

## Default working loop

**Research → Idea → Prototype → Test → Learn → Next experiment**

Before substantial work, ask:

> **What will we be able to do, demonstrate or know after this that we cannot do or know now?**

If the answer is unclear, reconsider the work.

## Forward progress

Everything should move the project toward greater capability or useful learning.

For normal proof-of-concept development:

- implement the main path first;
- use the smallest experiment that can answer the current question;
- add focused tests for working behaviour and bugs actually encountered;
- accept documented limitations;
- reuse existing code when it helps and bypass historical machinery when it does not;
- refactor when existing code obstructs the next useful experiment, not merely because it could be cleaner;
- move to the next useful experiment once the current one teaches us enough.

A newly discovered issue is not automatically the next task. Fix it now only when it prevents the current experiment, makes its result materially misleading, creates a real destructive/security risk, or blocks the next useful experiment. Otherwise record it briefly and continue.

Do not allow repeated review, correction, hardening and further-review cycles to replace capability development.

## Capability-first rule

For implementation tasks, the primary output must be a **working capability or executable experiment**. Supporting work must remain proportionate to that capability.

Do not spend most of a capability task on refactoring, validation, compatibility, documentation, test expansion, defensive programming, architecture work or edge-case handling unless the requested capability cannot work or cannot be meaningfully tested without it.

If the requested capability works and the focused tests needed to trust the experiment pass, **stop**. Do not continue polishing merely because additional improvements are possible.

Do not improve unrelated code while completing a capability task. Do not convert discovered technical debt into immediate scope. Do not redesign architecture unless the current design prevents the experiment from working or prevents the next useful experiment.

### POC code may be temporary

Proof-of-concept code does not need to be the architecture we would ship. Throwaway scripts, hard-coded experimental data, narrow assumptions, small duplicated paths and intentionally limited implementations are acceptable when they are understandable and let us test an idea quickly.

Do not generalise experimental code solely to make it reusable. Generalise or refactor when repeated experiments demonstrate that doing so will make useful development faster or when the existing implementation is blocking progress.

## Automated review policy

Automated review, including Codex review, is advisory during proof-of-concept development.

Fix a finding immediately only if it makes the current experiment materially wrong, unusable, destructive, insecure in a realistic way, or prevents the next useful experiment. Defer maintainability, broader validation, compatibility, speculative edge-case and future-proofing work that does not affect the current learning.

Do not enter an automatic `review → fix everything → review again → harden → review again` loop. One automated review pass per meaningful capability change is normally enough.

## Product direction

Do not treat Primavera P6 or Microsoft Project as specifications for this product. Existing products may be studied, compared with, imported from or exported to later, but their semantics and architecture do not define ours.

Do not assume OR-Tools, CP-SAT, CPM, a particular AI model or the historical canonical schema is the final architecture. They are tools and experiments unless later evidence makes them part of the product.

The current scheduling hypothesis is also not settled architecture. Treat integrated resource/constraint scheduling, Work–Method–Execution, objective policies, trusted live state and decomposition strategies as hypotheses to test rather than structures to harden prematurely.

## Native-model boundary — active rule

The active product dependency direction is:

```text
external source -> adapter -> PM-Software native project model -> scheduler/core -> workspace
```

This remains a hard directional rule for active prototype work:

- `project/` owns the product's native project concepts;
- `scheduling/` consumes the native project model only;
- `adapters/` translate external formats into the native model;
- external-system types, field names and semantics must not leak into the scheduling engine merely for compatibility;
- do not add a Microsoft Project or P6 field to the native model just because that field exists externally;
- do not make the native workflow require MSPDI, MPP, XER or any other external scheduling format;
- native projects must remain creatable, persistable, editable and schedulable without Microsoft Project or P6.

If an adapter needs source-specific metadata for import/reporting, keep it in the adapter/import context unless a product experiment demonstrates that the concept belongs in the native model independently of that source system.

## Planning-model hypothesis — bounded Work–Method–Execution

Targeted research challenged the assumption that a planner must select one complete activity network before scheduling begins.

The first bounded falsification experiment has now run successfully. It compared all 8 authorised fixed activity networks against one model that held six work packages and finite execution methods. Across three changed-condition scenarios, the candidate matched the exhaustive fixed-network oracle and automatically reselected authorised methods without manual topology edits.

The observed decisions were:

- normal conditions: `SCAFFOLD / CRANE / NORMAL`, finish H37;
- crane unavailable H10-H18: `SCAFFOLD / SEGMENTED / NORMAL`, finish H41;
- specialist available earlier plus scaffold limit H09: `ROPE / CRANE / SPECIALIST`, finish H35.

The candidate represented the alternatives with 33 activity facts and 33 relationship facts once, versus 180 activity facts and 176 relationship facts across the eight materialised fixed networks.

This means the **bounded Work–Method–Execution hypothesis was not falsified** by the first experiment. It does not mean the architecture is final.

Active rule for follow-on work:

- activities remain executable primitives;
- a work package/outcome may have finite, explicitly authorised execution methods where a real choice exists;
- the engine may choose only among authorised methods, modes, resources, sequence and timing;
- it must not invent scope or arbitrary work methods;
- fixed activity networks remain a valid special case;
- do not introduce unrestricted HTN/PDDL/state-planning semantics;
- do not promote `work_method_experiment.py` wholesale into the production model merely because the small case passed;
- add native WorkPackage/ExecutionMethod concepts only when the next useful experiment needs them.

The experiment is deliberately isolated in `src/deterministic_scheduling_core/work_method_experiment.py`.

## Execution-state hypothesis — trusted live project state

Targeted research challenged direct field-to-schedule mutation. The bounded falsification experiment compares incoming reports that immediately mutate authoritative schedule state against an event/provenance boundary that materialises only validated facts and assumptions into trusted project state before calling the unchanged native scheduler.

Observed result on the 20-activity case:

- direct mutation performed 7 authoritative replans, including 4 from unvalidated reports;
- 3 report-driven states were later corrected;
- those later-corrected reports caused 22 moved starts and 48h15m of temporary start movement;
- the trusted-state path performed 4 provisional impact calculations and 4 authoritative replans, with 0 authoritative replans from unvalidated reports;
- both paths reached the same final 11h30m handover after the same accepted facts were applied;
- validated actual history remained fixed, remaining duration remained a forecast assumption, emergent repair waited for explicit scope approval, and reordered delivery reproduced the same trusted-state and plan hashes.

The **trusted-live-state hypothesis was not falsified** by this bounded experiment.

Active rule for follow-on work:

- treat the live object as project state, not a schedule database receiving raw field edits;
- unvalidated reports may drive provisional impact analysis but must not silently become authoritative schedule truth;
- distinguish historical actuals from current operational facts, forecast assumptions and future planning decisions;
- validated history may be corrected through explicit superseding/correction information, but the scheduler must not optimise it away;
- do not infer approved emergent scope merely from an inspection finding;
- preserve occurrence time separately from receipt time where field information may arrive late/out of order;
- do not turn the whole application into an event-sourced system;
- do not promote the experiment's `FieldEvent`/`TrustedProjectState` classes wholesale into the production model merely because the bounded case passed;
- add native field/provenance concepts only when the next useful experiment needs them.

The experiment is deliberately isolated in `src/deterministic_scheduling_core/trusted_state_experiment.py`.

## Objective-policy hypothesis — aspiration-bounded recovery

Targeted research challenged the assumption that the mathematically earliest feasible finish should always define the authoritative plan. The bounded falsification experiment now tests an explicit hierarchy on the existing 33-possible-activity Work–Method problem rather than building a generic policy framework first.

The tested stages are:

```text
protected commitment lateness
        ↓
controlling finish → F*
        ↓
Finish ≤ F* + Δfinish
        ↓
approved execution-method changes
        ↓
materially moved activity count
        ↓
absolute start movement
        ↓
canonical tie-break
```

The approved plan is `SCAFFOLD / CRANE / NORMAL`, finish H37. A crane outage at H11-H16 creates a recovery trade-off while the protected H42 handoff remains achievable.

Observed result:

- `Δfinish = 0h`: `SCAFFOLD / SEGMENTED / NORMAL`, finish H41, 1 method change, 11 moved starts, 44h total start movement;
- `Δfinish = 1h`: `SCAFFOLD / CRANE / NORMAL`, finish H42, 0 method changes, 14 moved starts, 70h total start movement;
- both decisions match exhaustive enumeration of all 8 authorised fixed-network recoveries;
- all candidate optimisation stages were proven `OPTIMAL`;
- repeating the 1h policy produced the same canonical result;
- plausible finish-heavy and stability-heavy weighted scores selected different plans.

The **aspiration-bounded objective-policy hypothesis was not falsified** by this bounded experiment.

Active rule for follow-on work:

- actual history, frozen decisions, physical/logical feasibility and genuinely non-negotiable gates remain constraints, not tradeable objective penalties;
- protected commitments may sit above ordinary completion objectives when project policy explicitly says so;
- establish the best controlling finish before applying any authorised completion degradation;
- represent allowed degradation explicitly as a policy tolerance, not hidden solver weights;
- structural disruption and temporal movement are different dimensions;
- the current bounded hypothesis places structural method preservation above temporal movement only after completion is inside the authorised envelope;
- do not treat that exact lower-order ordering as universal: in this experiment the zero-method-change H42 plan moved more retained activities and more total time than the H41 method-changing plan;
- objective explanations should come from the stored policy stages and objective vector rather than fabricated narrative;
- weighted sums may be useful inside coherent tiers but must not silently become the universal project policy;
- do not promote a large `PlanningPolicy` schema or multi-objective framework merely because this experiment passed.

The experiment is deliberately isolated in `src/deterministic_scheduling_core/objective_policy_experiment.py`.

## Current position

Gate 1 through Gate 5 are provisionally demonstrated.

Prototype 1 proved a real MSPDI schedule could expose a real resource decision to the experimental core; that experiment is complete.

Prototype 2 established a PM-Software-owned native project that can be created, persisted, edited and scheduled without Microsoft Project or P6.

The Work–Method–Execution experiment showed, on a bounded synthetic case, that integrated selection of authorised execution structure can match the best of exhaustively enumerated fixed networks and react to changed resources/constraints without manual network reconstruction.

The trusted-live-state experiment then showed that provisional field information can remain visible and useful without contaminating the authoritative forecast, while accepted facts reconstruct the same final schedule deterministically.

The objective-policy experiment then showed that one explicit completion-tolerance decision can switch the authoritative recovery between true fastest and structurally stable plans for inspectable reasons, matching exhaustive enumeration in both cases.

CP-SAT remains the primary experimental optimisation backend for now, but the native model must remain solver-independent. Classical CP is a future challenger if richer calendar/state semantics become materially difficult to represent cleanly.

The next work should continue attacking the core planning architecture rather than defaulting to UI or compatibility work. High-value unresolved questions include:

- **scale/decomposition:** how large professional schedules should be partitioned or repaired incrementally;
- **CPM/criticality semantics:** what analytical role CPM, float and executable flexibility should have after integrated scheduling;
- **calendar/state scheduling semantics:** only if richer operational calendars/states become a real capability requirement;
- **objective ordering:** further evidence may still change the exact ordering between structural and temporal stability.

Prefer one targeted research question or executable experiment at a time.

## Historical Microsoft Project machinery

Unless explicitly required by a new experiment, do not add or extend the historical `native/msproject`, `native-validation`, protocol, register, manifest or compatibility machinery.

It is retained as research history and possible source material. It is not the architecture to build on.

`prototype1_workspace.py` is a completed real-file bridge. It routes MSPDI through the native model and scheduler. Do not turn it into a general Microsoft Project importer.
