# Deterministic Execution Contract `deterministic-v0.1`

## Promise boundary

The initial contract is deliberately narrow:

> The same canonical input, semantic model, application version, solver build, parameter set, execution profile and objective policy must produce the same canonical selected schedule and the same structured explanation.

The project does not initially promise reproducibility across solver versions, semantic-model versions, objective-policy versions, arbitrary worker counts, hardware architectures or native scheduler versions.

## Execution identity

The execution identity is the SHA-256 digest of canonical JSON containing:

- canonical input hash;
- source snapshot identifier;
- schema version;
- semantic-profile version;
- CPM-kernel version;
- constraint-model version;
- objective-policy version;
- solver name and build;
- solver parameters;
- worker count;
- random seed;
- search strategy;
- time/branch limit;
- warm-start identifier;
- tie-breaking policy;
- execution-platform fingerprint.

## Canonicalisation

- UTF-8;
- Unicode normalisation: NFC;
- keys sorted lexicographically;
- no insignificant whitespace;
- integers used for time and capacity in the executable model;
- arrays retain declared semantic order only where order is meaningful;
- otherwise arrays are sorted by stable ID before hashing;
- no floating-point time arithmetic;
- SHA-256 for input, output, selected scenario, explanation and evidence-bundle hashes.

The implementation may use RFC 8785-style canonical JSON, but the actual library and version must be pinned before execution.

## Search controls

Initial deterministic experiments use:

- one solver worker;
- fixed random seed `0`;
- no wall-clock-dependent termination for semantic cases;
- a declared deterministic tie-break;
- a pinned solver build;
- no unrecorded warm start.

Parallel search may be tested separately but cannot enter the deterministic claim until repeated-result equality is demonstrated.

## Required execution record

The machine-readable contract is `schemas/execution-record.schema.json`, schema revision `0.1.2`. Every record contains the following fields, even where their value is null or `not_applicable`:

- schema version;
- execution ID and case ID;
- execution timestamp;
- execution identity;
- result status;
- canonical input hash;
- complete output hash;
- selected-scenario hash;
- structured-explanation hash;
- evidence-bundle hash;
- independent validator result;
- feasibility status;
- optimality status;
- complete integer objective vector;
- best bound and absolute optimality gap where available;
- native round-trip result where applicable;
- evidence paths;
- optional failure code and notes.

## Result-status rules

The allowed result labels are:

- `executed_pass`;
- `executed_fail`;
- `executed_inconclusive`;
- `not_executed`;
- `not_accessible`;
- `native_validation_required`;
- `practitioner_validation_required`;
- `buyer_validation_required`.

No record may use an `executed_*` status without:

- a non-null execution timestamp;
- a non-null execution identity and input hash;
- a non-null evidence-bundle hash;
- at least one evidence path;
- a completed validator result (`pass` or `fail`);
- completed feasibility and optimality classifications.

An `executed_pass` additionally requires:

- a non-null complete output hash;
- a non-null selected-scenario hash;
- a non-null explanation hash;
- validator status `pass`;
- feasibility status `feasible` or `not_applicable`;
- optimality status `optimal`, `feasible_not_proven` or `not_applicable`.

An optimal or feasible-not-proven result must be feasible. An infeasible-proven result must be classified infeasible; contradictory feasibility and optimality states are invalid.

A failed or inconclusive execution may lack a selected scenario when failure occurred before one was produced, but the immutable failure evidence bundle remains mandatory.

Non-executed result labels must not contain an input, execution, output, selected-scenario, explanation or evidence-bundle hash, and must not claim that validation ran. `native_validation_required` must explicitly record a native round-trip status of `required_not_run`.


## Counterfactual execution evidence

A counterfactual is a separate recomputation, not narrative inference. A feasible counterfactual must contain a validated output hash, a non-empty objective vector and validator status `pass`. A proven-infeasible counterfactual records no output schedule, an empty objective vector and validator status `pass`. The changed input, execution identity, result evidence hash and evidence paths remain mandatory in both cases.

## Native round-trip record

Where native round-trip is attempted, record:

- status: pass, fail or inconclusive;
- native system;
- hash of the saved round-trip evidence;
- optional notes.

Where native testing does not apply, record `not_applicable` rather than omitting the field.

## Failure rule

If the same execution identity produces a different selected-schedule hash or explanation hash, the deterministic gate fails. The result must not be hidden through narrative post-processing.
