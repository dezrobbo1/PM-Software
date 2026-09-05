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

The current scheduling hypothesis is also not settled architecture. Treat integrated resource/constraint scheduling, Work–Method–Execution, objective policies and decomposition strategies as hypotheses to test rather than structures to harden prematurely.

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

## Current position

Gate 1 through Gate 5 are provisionally demonstrated.

Prototype 1 proved a real MSPDI schedule could expose a real resource decision to the experimental core; that experiment is complete.

Prototype 2 established a PM-Software-owned native project that can be created, persisted, edited and scheduled without Microsoft Project or P6.

The Work–Method–Execution experiment then showed, on a bounded synthetic case, that integrated selection of authorised execution structure can match the best of exhaustively enumerated fixed networks and react to changed resources/constraints without manual network reconstruction.

The next work should continue attacking the core planning architecture rather than defaulting to UI or compatibility work. High-value unresolved questions include:

- **objective architecture:** what makes one feasible executable plan better than another;
- **solver architecture:** whether CP-SAT remains the best engine or one backend in a hybrid;
- **scale/decomposition:** how large professional schedules should be partitioned or repaired incrementally;
- **CPM/criticality semantics:** what analytical role CPM, float and executable flexibility should have after integrated scheduling.

Prefer one targeted research question or executable experiment at a time.

## Historical Microsoft Project machinery

Unless explicitly required by a new experiment, do not add or extend the historical `native/msproject`, `native-validation`, protocol, register, manifest or compatibility machinery.

It is retained as research history and possible source material. It is not the architecture to build on.

`prototype1_workspace.py` is a completed real-file bridge. It routes MSPDI through the native model and scheduler. Do not turn it into a general Microsoft Project importer.
