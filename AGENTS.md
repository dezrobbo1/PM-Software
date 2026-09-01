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

## Product direction

Do not treat Primavera P6 or Microsoft Project as specifications for this product. We are researching something new. Existing products may be studied, compared with, imported from or exported to later, but their semantics and architecture do not define ours.

Do not assume OR-Tools, CP-SAT, CPM, a particular AI model or the current canonical schema is the final architecture. They are tools and experiments unless later evidence makes them part of the product.

## Historical machinery

Unless explicitly required by the current experiment, do not add or extend protocol versions, evidence registers, whole-repository manifests, native Microsoft Project/P6 automation, compatibility programmes, provenance frameworks, production hardening or speculative edge-case handling.

The numbered Phase 0 documents, registers, native-validation material and archived workflows are historical research references. They do not block proof-of-concept development.

## Current gate

The project is currently at **Gate 1 — Core works**.

The immediate experiment should be small enough to run and inspect: roughly 10–30 activities with durations, precedence and constrained shared resources, producing a readable feasible schedule and a simple comparison/baseline.

The objective is to learn whether the deterministic AI core idea is worth taking to Gate 2, not to make Gate 1 production-ready.
