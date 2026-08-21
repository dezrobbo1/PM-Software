# Phase 0 Amendment `phase0-0.1.3` — Remaining Review Corrections

Date: 17 August 2026
Source: remaining Codex review threads on PR #1
Evidence state: no CPM kernel, optimiser, native application comparison, practitioner evaluation or buyer test had been executed.

## Accepted findings

The remaining review identified that the previous guard layer still permitted or failed to detect:

1. reversed saved schedule-state intervals;
2. an attempted native round trip labelled with no real native system;
3. catalogue metadata drifting from its fixture;
4. multi-node WBS cycles;
5. in-progress activities without remaining duration;
6. caller-supplied explanation movement inconsistent with the coordinates;
7. incomplete case-specific objective vectors;
8. invalid operational-constraint windows;
9. unvalidated deterministic-profile fields;
10. `actual_dates` fixtures presented as declared reference results;
11. incomplete proposed-scenario activity coverage;
12. approved scenarios without approval governance;
13. drift in the reference semantic profile or fixture profile reference;
14. positive-duration execution modes on milestones;
15. actual finish without a valid actual start interval;
16. non-zero expected milestone spans;
17. normal tasks entering the mandatory-milestone objective predicate;
18. an undefined combined level-five penalty;
19. passing execution records without explicit native-round-trip disposition;
20. continued use of obsolete canonical schema version `0.1.0` after material expansion;
21. missing or extra numbered protocol chapters being silently omitted from the consolidated document;
22. saved scenario dates that did not consume the selected activity or mode duration over selected calendars;
23. declared expected dates beyond the fixture horizon;
24. an `optimal` result with a non-zero optimality gap;
25. calculation traces without machine-verifiable trace evidence;
26. regression risk to valid semantic executions whose feasibility and optimality are legitimately not applicable.
27. proposed scenarios moving activities whose coordinates are frozen;
28. the active reference profile claiming unexercised `fixed_start` and `fixed_finish` semantics;
29. explanation causes and milestone impacts that did not resolve against the canonical input;
30. evidence registers retaining their filenames while silently losing required columns;
31. malformed JSON Pointer escapes in counterfactual input patches;
32. in-progress activities without a deterministic status-time origin.

The one-time automated correction attempt also introduced unsafe proposals—forcing a fixed seven-entry objective vector and replacing the proposed-scenario definition with the wrong state type. Those proposals were not retained.

## Corrections

- Introduced active canonical, execution and explanation schema revision `0.1.3`.
- Migrated all 50 fixtures to canonical schema `0.1.3` and assigned stable IDs to the 13 existing date constraints without altering calculation-bearing values or expected results.
- Preserved historical `reference-v0.1`, introduced active `reference-v0.2`, and removed untested fixed-date constraint claims until direct fixtures exist.
- Introduced `objective-v0.3`; retained v0.1 and v0.2 as superseded historical preregistrations.
- Defined the complete case-derived objective-vector layout, including exact mandatory-milestone grouping and canonical activity/resource tie fields.
- Defined level five as a lexicographically ordered tuple and made unsupported overtime/continuity components explicitly zero until a new model version supports them.
- Added full semantic-profile and deterministic-profile equality checks.
- Added WBS-cycle, actual-state, status-time, operational-window, state-span, scenario-completeness, frozen-coordinate, approval-governance, horizon, native-round-trip, optimality and explanation cross-validation.
- Resolved explanation causes and milestone impacts against canonical entity namespaces and restricted counterfactual patches to valid RFC 6901 paths.
- Froze the exact column sequence for every evidence register.
- Made the fixture catalogue and numbered protocol chapter set exact mirrors of their authoritative sources.
- Added 32 regression tests, increasing the suite from 21 to 53.
- Removed the failed one-time applicator and temporary export workflow.

## Outcome classification

- Existing calculation-bearing activity, relationship, resource, calendar and expected-result values: unchanged; date constraints received stable traceability IDs.
- Reference semantic meaning: historical `reference-v0.1` is preserved; active `reference-v0.2` is deliberately narrower because two previously claimed fixed-date constraints had no direct fixture coverage.
- Objective policy: superseded from incomplete v0.2 to executable v0.3 before results existed.
- Canonical schema: migrated from v0.1.0 to v0.1.3 because the expanded schema is not backward-identical.
- Prior benchmark evidence: none existed and none was rewritten.
