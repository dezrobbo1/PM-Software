# Phase 0 Change Control

## Freeze rule

The initial protocol was frozen at `phase0-0.1.0` before scheduling results existed.

Any change to semantics, objective levels, tie-breaking, comparator settings, metrics, case inputs, expected outputs, pass criteria or exclusions must:

1. receive a new version;
2. state the reason;
3. identify whether results already existed when the change was proposed;
4. list affected cases and prior outputs;
5. preserve the superseded version or its immutable Git history;
6. regenerate the consolidated protocol and manifest;
7. never overwrite unfavourable evidence.

## Change classes

- `editorial`: no semantic or benchmark effect;
- `clarification`: resolves ambiguity without changing expected result;
- `semantic`: changes calculation meaning;
- `benchmark`: changes case, comparator or metric;
- `deterministic`: changes execution identity or canonicalisation;
- `scope`: changes included or excluded capability;
- `validation`: strengthens machine enforcement without changing a valid declared result.

## Phase 0 amendment `phase0-0.1.1`

Date: 16 August 2026  
Trigger: Codex review of PR #1  
Results existing when proposed: **none**

Classes: clarification, deterministic and validation.

The amendment:

- replaces ambiguous objective policy `objective-v0.1` with fully specified `objective-v0.2` while preserving v0.1;
- aligns the canonical, execution-record and structured-explanation schemas with their written contracts;
- requires evidence hashes and completed validation for executed results;
- adds every benchmark result label to the execution schema;
- enforces zero-duration milestones and unit-capacity exclusive resources;
- validates duplicate IDs, lag-calendar references, working intervals and complete expected results;
- makes the manifest cover exactly the intended tracked repository file set;
- adds negative regression tests and continuous validation.

Affected semantic fixtures: none of the 50 inputs or expected outputs changed.  
Affected prior outputs: none; no CPM, optimiser, native or practitioner execution had occurred.

The detailed amendment record is `docs/amendments/phase0-0.1.1-review-corrections.md`.

## Phase 0 amendment `phase0-0.1.2`

Date: 16 August 2026  
Trigger: follow-up Codex review of PR #1  
Results existing when proposed: **none**

Classes: clarification, deterministic and validation.

The amendment:

- requires null input hashes for every non-executed result;
- validates scenario-state resource assignments and state-coordinate integrity;
- requires validated output and objective evidence for feasible counterfactuals;
- enables RFC 3339 date-time format checking;
- validates exact objective-policy values and ordered levels, not only key presence;
- binds baseline and approved-forecast state types to their containing fields;
- rejects contradictory feasibility and optimality classifications;
- requires explicit coordinates for frozen activities;
- requires the complete frozen register set;
- adds nine corresponding negative regression tests.

Affected semantic fixtures: none of the 50 inputs or expected outputs changed.  
Affected prior outputs: none; no CPM, optimiser, native or practitioner execution had occurred.

The detailed amendment record is `docs/amendments/phase0-0.1.2-follow-up-review-corrections.md`.

## Pre-registration rule

Before each new benchmark family begins, commit:

- hypothesis;
- corpus;
- comparator configuration;
- metrics;
- stop limit;
- pass interpretation;
- evidence location.

Post-result changes must be explicitly labelled exploratory and cannot replace the preregistered result.
