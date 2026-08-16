# Deterministic Execution Contract `deterministic-v0.1`

## Promise boundary

The initial contract is deliberately narrow:

> The same canonical input, semantic model, application version, solver build, parameter set, execution profile and objective policy must produce the same canonical selected schedule and the same structured explanation.

The project does not initially promise reproducibility across solver versions, semantic-model versions, objective-policy versions, arbitrary worker counts, hardware architectures or native scheduler versions.

## Execution identity

The execution identity is the SHA-256 digest of canonical JSON containing:

- canonical input hash
- source snapshot identifier
- schema version
- semantic-profile version
- CPM-kernel version
- constraint-model version
- objective-policy version
- solver name and build
- solver parameters
- worker count
- random seed
- search strategy
- time/branch limit
- warm-start identifier
- tie-breaking policy
- execution-platform fingerprint

## Canonicalisation

- UTF-8
- Unicode normalisation: NFC
- keys sorted lexicographically
- no insignificant whitespace
- integers used for time and capacity in the executable model
- arrays retain declared semantic order only where order is meaningful
- otherwise arrays are sorted by stable ID before hashing
- no floating-point time arithmetic
- SHA-256 for input, output and explanation hashes

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

## Required output record

- execution identity
- feasibility status
- optimality status
- objective vector
- best bound or gap where available
- selected scenario hash
- structured explanation hash
- validator result
- native round-trip result where applicable

## Failure rule

If the same execution identity produces a different schedule hash or explanation hash, the deterministic gate fails. The result must not be hidden through narrative post-processing.
