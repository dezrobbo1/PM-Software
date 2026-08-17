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

## Frozen profile definition

`config/deterministic-execution-profile-v0.1.json` is validated as one complete immutable object. Validation does not check only the tie-break field. Worker count, seed, normalisation, hash algorithm, time representation, termination policy, solver placeholders, tie-break reference and cross-version promise are all frozen values.

Before the first execution, the placeholder canonical-JSON implementation and solver build must be replaced through change control with pinned executable values and a new deterministic-profile version.

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
- the declared `objective-v0.3` canonical tie-break;
- a pinned solver build;
- no unrecorded warm start.

Parallel search may be tested separately but cannot enter the deterministic claim until repeated-result equality is demonstrated.

## Required execution record

The machine-readable contract is `schemas/execution-record.schema.json`, schema revision `0.1.3`. Every record contains the following fields, even where their value is null or `not_applicable`:

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
- complete case-specific integer objective vector;
- best bound and absolute optimality gap where available;
- explicit native round-trip disposition;
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
- optimality status `optimal`, `feasible_not_proven` or `not_applicable`;
- an explicit native round-trip object whose status is attempted, required-not-run or not-applicable.

An optimal or feasible-not-proven result must be feasible. An optimal result has absolute optimality gap exactly `0`. A proven-infeasible result must be classified infeasible. A non-optimisation semantic execution may remain `not_applicable` for feasibility and optimality and uses an empty objective vector.

The cross-validator derives the complete objective-vector length from the case's mandatory milestone groups, activities, modes and resources. Merely requiring a non-empty array is insufficient.

A failed or inconclusive execution may lack a selected scenario when failure occurred before one was produced, but the immutable failure evidence bundle remains mandatory.

Non-executed result labels must not contain an input, execution, output, selected-scenario, explanation or evidence-bundle hash and must not claim that validation ran. `native_validation_required` must explicitly record a native round-trip status of `required_not_run`.

## Counterfactual execution evidence

A counterfactual is a separate recomputation, not narrative inference. A feasible counterfactual must contain a validated output hash, a non-empty objective vector and validator status `pass`. A proven-infeasible counterfactual records no output schedule, an empty objective vector and validator status `pass`. An unknown result cannot claim an output or objective vector. The changed input, execution identity, result evidence hash and evidence paths remain mandatory.

Counterfactual input changes use non-empty RFC 6901 JSON Pointer paths. Only `~0` and `~1` are valid escape sequences; malformed pointers are rejected before any recomputation is accepted.

## Native round-trip record

Where native round-trip is attempted, record:

- status: `pass`, `fail` or `inconclusive`;
- native system: `p6`, `microsoft_project` or an identified `other` system;
- hash of the saved round-trip evidence;
- optional notes.

An attempted round trip cannot name its native system `not_applicable`. A `required_not_run` record identifies the intended real native system but has no evidence hash. Where native testing does not apply, use status and system `not_applicable` with a null evidence hash.

## Structured explanation and calculation traces

The machine-readable explanation schema is revision `0.1.3`.

- An optimisation explanation contains a scenario ID, complete case-specific objective vector, recomputed counterfactual evidence and explicit null calculation-trace disposition.
- A calculation trace contains no optimisation scenario or counterfactual vector. It must instead carry a validated calculation-trace record identifying the rule, inputs, derived coordinates, recomputation hash and evidence paths.
- `movement` is recomputed from the declared coordinate pair selected by `movement_basis`; a caller cannot write `movement: 0` to avoid causal requirements.
- Every governing relationship, calendar, activity, resource, operational constraint, objective policy or actual event resolves against the hashed canonical input. Conflicting activities, affected milestones and counterfactual milestone impacts must also resolve, and milestone references must identify actual milestone activities.

## Failure rule

If the same execution identity produces a different selected-schedule hash or explanation hash, the deterministic gate fails. The result must not be hidden through narrative post-processing.
