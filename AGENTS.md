# PM-Software working mode

This repository is an exploratory R&D project built around the **deterministic AI core** idea. Read the root `README.md` before substantial work; it defines the current mission and progress gates.

## Default working loop

**Research → Idea → Prototype → Test → Learn → Next experiment**

Research and new ideas are encouraged, including unconventional approaches. When an idea can be tested cheaply, prefer a small working experiment over extended theoretical preparation.

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

When choosing between extending a working experiment and making the current implementation more complete or robust, prefer the next useful experiment unless the extra robustness is necessary to trust the result.

### POC code may be temporary

Proof-of-concept code does not need to be the architecture we would ship.

Throwaway scripts, hard-coded experimental data, narrow assumptions, small duplicated paths and intentionally limited implementations are acceptable when they are understandable and let us test an idea quickly.

Do not generalise experimental code solely to make it reusable. Generalise or refactor when repeated experiments demonstrate that doing so will make useful development faster or when the existing implementation is blocking progress.

A limitation that is visible and understood is acceptable during R&D. The goal is to learn whether the idea works before investing in making it complete.

## Automated review policy

Automated review, including Codex review, is **advisory during proof-of-concept development**. A review comment is not automatically a blocker and does not automatically expand the task.

For each finding, make one decision:

- **Fix now** only if it makes the current experiment materially wrong, unusable, destructive, insecure in a realistic way, or prevents the next useful experiment.
- **Defer** if it is a maintainability improvement, broader validation request, compatibility concern, speculative edge case, production-hardening issue or future-proofing suggestion that does not affect the current experiment.
- **Reject** if it conflicts with the current research goal or would add complexity without useful learning.

Do not enter an automatic `review → fix everything → review again → harden → review again` loop.

Normal rule: **one automated review pass per meaningful capability change**. After that pass, fix only findings that meet the "Fix now" test above. Do not request another automated review solely to obtain a clean review unless the fixes materially changed the capability or the user explicitly asks for another review cycle.

A PR may be merged with deferred automated-review findings during proof-of-concept work when the implemented experiment works, the focused tests pass, and the deferred findings do not invalidate what the experiment is intended to teach us.

Review quality is not measured by the number of findings resolved. Project progress is measured by capability and useful learning.

## Product direction

Do not treat Primavera P6 or Microsoft Project as specifications for this product. We are researching something new. Existing products may be studied, compared with, imported from or exported to later, but their semantics and architecture do not define ours.

Do not assume OR-Tools, CP-SAT, CPM, a particular AI model or the current canonical schema is the final architecture. They are tools and experiments unless later evidence makes them part of the product.

## Historical machinery

Unless explicitly required by the current experiment, do not add or extend protocol versions, evidence registers, whole-repository manifests, native Microsoft Project/P6 automation, compatibility programmes, provenance frameworks, production hardening or speculative edge-case handling.

The numbered Phase 0 documents, registers, native-validation material and archived workflows are historical research references. They do not block proof-of-concept development.

## Current gate

Gate 1, Gate 2 and Gate 3 are provisionally demonstrated by working experiments.

The project is now at **Gate 4 — Change and replanning**.

The next experiment should begin with an already feasible plan, introduce one small realistic execution disturbance, and produce a revised plan that remains feasible under the existing operational constraints.

Prefer one transparent perturbation such as a short `CRANE-C04` unavailability or a changed remaining duration. The useful question is whether the core can respond sensibly, preserve unaffected work where possible, and explain the important downstream change.

Do not turn Gate 4 into a general progress engine, event architecture, baseline/change-control framework or production replanning platform. Build the smallest experiment that tells us whether replanning is useful.

Do not harden or generalise the Gate 1/2/3 experiments before moving forward unless a discovered defect materially invalidates their learning.
