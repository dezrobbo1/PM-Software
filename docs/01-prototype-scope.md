# Prototype Scope

## Purpose

Build the smallest executable research instrument capable of falsifying the proposition that a reproducible constraint-optimisation layer can improve selected professional scheduling decisions.

The prototype is a calculation and benchmark service, not a project-management product.

## Included in the bounded prototype

- Stable project, WBS and activity identifiers
- Activities and zero-duration milestones
- FS, SS, FF and SF relationships
- Positive and negative lag
- Explicit working-time calendars
- Actual start and actual finish preservation
- Remaining duration and status/data time
- A versioned reference semantic profile
- Separate future P6 and Microsoft Project compatibility profiles
- Renewable cumulative resources
- Named resources and equipment
- Skills and eligibility sets
- Exclusive resources
- Workface occupancy
- Permit and time windows
- SIMOPS exclusions
- Alternative execution modes
- Frozen near-term horizon
- Mobilisation penalty
- Declared lexicographic objectives
- Canonical tie-breaking
- Independent semantic and feasibility validation
- Structured machine-verifiable explanation
- Canonical input, output and explanation hashes
- Read-only scenario comparison
- Controlled native export experiments only after validation

## Explicitly excluded from the initial prototype

- General project-management user interface
- Portfolio management
- Cost accounting or earned-value suite
- Document management
- Chat, collaboration or workflow platform
- Generative schedule authoring
- Monte Carlo or quantitative schedule-risk analysis
- Full P6 semantic parity
- Full Microsoft Project semantic parity
- Binary MPP implementation
- Autonomous mutation of a native authoritative schedule
- Production deployment
- Claims of cross-version solver determinism
- Claims of global optimisation for 25,000–50,000 activities

## Authority boundary

Until native semantic parity and round-trip safety are demonstrated:

- the native schedule remains authoritative;
- the prototype produces a proposed scenario only;
- an independent validator may reject the scenario;
- native recalculation may reject the scenario;
- human approval remains mandatory.

## Initial solver boundary

OR-Tools CP-SAT is the first research candidate. An exact version is not selected in Phase 0; it must be pinned before the first optimiser result is generated. IBM CP Optimizer is a desirable independent comparator subject to confirmed licensing and access.
