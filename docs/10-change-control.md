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

## Phase 0 amendment `phase0-0.1.3`

Date: 17 August 2026
Trigger: remaining Codex review of PR #1 and review of the failed one-time correction attempt
Results existing when proposed: **none**

Classes: clarification, semantic-profile binding, deterministic, objective-policy, schema migration and validation.

The amendment:

- advances all active machine-readable schemas to revision `0.1.3`, migrates all 50 fixtures to canonical schema `0.1.3`, and assigns stable IDs to existing date constraints without changing calculation-bearing values or declared expected results;
- supersedes incomplete `objective-v0.2` with exact `objective-v0.3`, including the mandatory milestone kind predicate, explicit level-five tuple and case-specific canonical tie vector;
- preserves historical `reference-v0.1`, supersedes it with active `reference-v0.2`, and removes untested `fixed_start`/`fixed_finish` executable claims rather than inventing fixture coverage;
- freezes every field of the active reference semantic profile and deterministic profile;
- requires exact fixture/catalogue agreement and the exact numbered protocol chapter set;
- rejects WBS cycles, invalid actual-state combinations, milestone modes with duration, invalid operational windows and out-of-horizon expected results;
- validates complete proposed-scenario activity coverage, frozen-coordinate preservation, approval governance, objective-vector shape and saved state duration/calendar satisfaction;
- validates in-progress status-time origin, coordinate-derived explanation movement, canonical cause namespaces, RFC 6901 counterfactual paths and explicit calculation-trace evidence;
- freezes the exact header sequence of every evidence register;
- requires explicit native round-trip disposition for passing executions and zero optimality gap for `optimal` results;
- removes the failed one-time applicator and temporary export workflow;
- adds 32 corresponding regression tests, bringing the guard suite to 53 tests.

Affected semantic fixtures: their schema-version field changed from `0.1.0` to `0.1.3`, their semantic-profile reference changed from superseded `reference-v0.1` to active `reference-v0.2`, and 13 existing date constraints received stable IDs. All calculation-bearing duration, relationship, calendar, resource, project and expected-result values are unchanged.
Affected prior outputs: none; no CPM, optimiser, native or practitioner execution had occurred.

The detailed amendment record is `docs/amendments/phase0-0.1.3-remaining-review-corrections.md`.

## Phase 0 amendment `phase0-0.1.4`

Date: 17 August 2026
Trigger: fresh Codex review of PR #1
Results existing when proposed: **none**

Classes: semantic-profile binding, schema revision, benchmark identity freeze and validation.

The amendment:

- machine-validates all declared relationship formulas and signed successor-calendar lag against the expected oracle;
- freezes the exact 50 fixture identities and canonical filename mapping;
- preserves historical `reference-v0.1` and `reference-v0.2`, introduces active `reference-v0.3`, and removes untested alternate-lag-calendar and cumulative-capacity execution claims;
- requires complete activity coverage for every supplied approved forecast and proposed scenario;
- advances the execution-record schema to `0.1.4` and rejects selected-scenario/objective/bound/gap evidence for `infeasible_proven` results;
- independently recomputes all 49 declared coordinate oracles, including duration, date-bound, status, calendar and canonical-earliest placement;
- checks exclusive-resource feasibility and independently objective-selects the two frozen contended-resource orders;
- recomputes every objective-vector value from complete feasible selected states for proposed scenarios, execution evidence and patched feasible counterfactuals;
- recomputes complete float values for the two restricted float fixtures;
- freezes each curated driving-relationship assertion set and verifies that every listed relationship governs after calendar adjustment; and
- adds focused negative regression tests, bringing the guard suite to 67 tests.

Affected semantic fixtures: only the active semantic-profile reference changed from `reference-v0.2` to `reference-v0.3`. All calculation-bearing values and declared expected results remain unchanged.
Affected prior outputs: none; no CPM, optimiser, native or practitioner execution had occurred.

The detailed amendment record is `docs/amendments/phase0-0.1.4-executable-claim-and-oracle-hardening.md`.
