# Deterministic Scheduling Core — Phase 0 Protocol

This consolidated review document mirrors the authoritative files in this bundle. The individual files remain the change-controlled source.


---

# Source Basis and Evidence Boundary

This Phase 0 bundle is grounded in the supplied project sources.

## Governing source conclusions

1. **State of Professional Project Scheduling Software: Strengths, Limitations and Unmet Needs**
   - P6 and Microsoft Project have mature CPM, calendar, relationship, baseline, resource and diagnostic capability.
   - Resource-constrained scheduling is not merely a basic arithmetic problem.
   - Interchange may be semantically lossy.

2. **Professional Scheduling in Practice: Practitioner Workflows, Trust, Workarounds and Unmet Needs**
   - The stronger problem is operational representation, causal synthesis and workflow integration rather than missing CPM features.
   - Expert practice and automatic levelling use vary; prevalence remains unmeasured.
   - Direct workflow observation is more valuable than another broad desk study.

3. **Professional Scheduling Practitioner Validation: Workflow Evidence, Decision Friction and Adoption Potential**
   - P6 or Microsoft Project should remain authoritative during initial validation.
   - Direct practitioner and buyer evidence remains required.
   - Native-feature, competitive, input-economics, trust and buyer gates are mandatory.

4. **Deterministic Constraint Scheduling Core versus CPM and Priority-Based Levelling: Technical Feasibility, Benchmark Performance and Product Differentiation**
   - Build a bounded technical prototype, not a replacement platform.
   - Compare principally against expert-configured native levelling and experienced planners, not only default settings.
   - Treat semantic parity, determinism, stability, interoperability, modelling economics, practitioner acceptance and buyer value as open gates.
   - Use an independent validator and keep the optimiser's output as a proposed scenario until native parity is proven.

## Evidence boundary

The source reports establish the need for the experiment and its design constraints. They do not establish benchmark outcomes. This bundle therefore uses the following labels:

- `declared`: a Phase 0 policy or specification;
- `source-supported`: a conclusion directly supported by supplied research;
- `native-validation-required`: cannot be established without running the native application;
- `experiment-required`: cannot be established without executable benchmarking;
- `practitioner-validation-required`: cannot be established without real participants;
- `buyer-validation-required`: cannot be established without budget-holding stakeholders.

No unexecuted result is represented as a finding.

---

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

---

# Reference Semantic Contract `reference-v0.1`

## Purpose

This contract defines a small, explicit scheduling model for independent prototype testing. It is not presented as P6 or Microsoft Project semantics.

## Time model

- All test calculations use integer time units.
- Each fixture declares the unit, origin and horizon.
- Calendars are explicit half-open working intervals `[start, finish)`.
- An activity may execute only inside its activity calendar and all mandatory assigned-resource calendars.
- Start and finish values are integer offsets from the declared origin.
- Canonical serialisation stores timezone-aware source timestamps separately when native data are imported.

## Duration

- Duration is productive working time.
- A task's finish is obtained by consuming its duration across allowed working intervals from its scheduled start.
- A zero-duration milestone has `start == finish`.
- An activity start bound that occurs outside working time is moved to the first allowed working instant.

## Relationship formulas

Let predecessor `i` and successor `j` have start `S` and finish `F`.

- FS: `S_j >= add_lag(F_i, lag)`
- SS: `S_j >= add_lag(S_i, lag)`
- FF: `F_j >= add_lag(F_i, lag)`
- SF: `F_j >= add_lag(S_i, lag)`

For `reference-v0.1`:

- lag is consumed on the successor activity calendar unless a fixture explicitly declares another calendar;
- positive lag adds working time;
- negative lag subtracts working time;
- all activities are bounded by project start unless an actual start precedes it;
- when several bounds apply, the latest feasible start governs;
- for finish-based bounds, the activity start is derived by subtracting its productive duration on its calendar.

P6 and Microsoft Project lag/calendar rules are not assumed equivalent and require separate native profiles.

## Constraints included in `reference-v0.1`

- `start_no_earlier_than`
- `finish_no_earlier_than`
- fixed actual start
- fixed actual finish
- frozen start/finish within a declared frozen horizon

Other native constraints remain outside the reference subset until explicitly specified.

## Actuals and status

- Actual start and actual finish are immutable historical facts.
- A completed activity uses its actual start and actual finish.
- An in-progress activity retains actual start and schedules remaining work no earlier than the status time unless a declared policy allows otherwise.
- `retained_logic`: remaining successor work waits for unfinished predecessor work.
- `progress_override`: remaining successor work may continue from status time despite unfinished predecessor logic.
- `actual_dates`: included as a native-validation case only in Phase 0; no unsupported equivalence is invented.

## Resources

- A cumulative resource has integer capacity.
- An exclusive resource has capacity one.
- Activity demand must not exceed capacity at any time.
- Resource calendar availability intersects with the activity calendar.
- Equal-quality choices are resolved by the declared objective policy and stable activity-ID tie-break.

## Float for reference micro-tests

Float is calculated only for simple 24x7 acyclic networks without actuals, resource constraints or date constraints:

- project finish is the maximum early finish;
- backward pass starts from project finish;
- total float is `late_start - early_start`;
- free float is the minimum successor early start minus activity early finish, or project finish minus early finish for a terminal activity.

No claim is made that this restricted float profile matches every native product configuration.

## Unsupported or unresolved semantics

The following require later, separate profiles:

- P6 retained-logic, progress-override and actual-dates parity beyond declared cases
- P6 relationship-lag calendar options
- Microsoft manual task scheduling
- native duration-type semantics
- resource-dependent activity/task types
- summary and level-of-effort semantics
- suspend/resume behaviour
- multiple float paths
- cross-project relationships
- full constraint hierarchies

Any unexplained native difference is a failed compatibility claim, not a reason to modify the reference result after the fact.

---

# Canonical Schedule Model

## Design principles

- Neutral representation first; native adapters are explicit transformations.
- Source-specific state is preserved rather than silently normalised away.
- Historical facts, approved forecast and proposed scenario are distinct.
- Every calculation is tied to an immutable source snapshot and versioned policy.
- Unsupported native semantics remain labelled and preserved where possible.

## Core entities

### Schedule

- `schema_version`
- `schedule_id`
- `name`
- `source_system`
- `source_snapshot_id`
- `source_file_hash`
- `semantic_profile`
- `time_axis`
- `project_start`
- `status_time`
- `required_finish`
- `wbs`
- `calendars`
- `resources`
- `activities`
- `relationships`
- `operational_constraints`
- `baseline`
- `approved_forecast`
- `proposed_scenario`
- `governance`

### Activity

- stable `id`
- `name`
- `wbs_id`
- `kind`: task, start milestone, finish milestone
- `duration`
- `remaining_duration`
- `calendar_id`
- `actual_start`
- `actual_finish`
- `constraints`
- `assignments`
- `eligible_modes`
- `frozen_state`
- `source_fields`

### Relationship

- stable `id`
- predecessor and successor IDs
- `type`: FS, SS, FF, SF
- signed lag
- lag-calendar policy
- source-system representation

### Resource

- stable `id`
- type: renewable, exclusive, cumulative, non-renewable
- capacity
- calendar
- skills/certifications
- location/work area
- source-system reference

### Operational constraint

- workface occupancy
- permit/time window
- isolation state
- SIMOPS exclusion
- material/release state
- mandatory supervision
- alternative crew or method
- continuity/minimum run
- mobilisation transition
- frozen horizon

### Scenario and governance

- immutable input snapshot
- objective-policy version
- model and solver versions
- proposed dates/resources/modes
- structured explanation
- alternatives and counterfactuals
- approval state
- actor and timestamp
- rejected/accepted decision

## Native mapping policy

Every mapped field is classified as:

- `lossless`
- `transformed_equivalent`
- `transformed_material_difference`
- `unsupported_preserved`
- `unsupported_lost`
- `manual_approval_required`

Successful file import is not treated as semantic equivalence.

The machine-readable schema is in `schemas/canonical-schedule.schema.json`.

---

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

---

# Benchmark Objective Policy `objective-v0.1`

This is a transparent experimental policy. It is not a validated universal planner preference.

## Lexicographic levels

1. Zero hard safety, temporal, calendar, resource and operational violations.
2. Minimise mandatory milestone lateness. Milestones are evaluated in descending `milestone_priority`; lateness at a higher priority is minimised before lateness at a lower priority.
3. Minimise project completion time.
4. Minimise movement from the approved forecast.
5. Minimise overtime, mobilisation events and resource peaks.
6. Minimise crew and workface continuity interruptions.
7. Resolve any remaining equality using stable ascending activity IDs and stable mode/resource IDs.

A lower level cannot improve at the expense of a higher level.

## Objective vector

The canonical vector is:

```text
[
  hard_violation_count,
  mandatory_milestone_lateness_by_descending_priority,
  project_finish,
  approved_forecast_movement,
  overtime_mobilisation_peak_penalty,
  continuity_interruption_penalty,
  canonical_tie_rank
]
```

Each element is an integer in the declared time/cost unit. No opaque weighted total is used for the initial benchmark.

## Required scenario comparison

For every candidate scenario, retain the full vector and separate metrics. Do not collapse quality, runtime, stability, modelling effort and practitioner acceptance into one composite score.

## Change control

Any change to level order, metric definition or tie-break creates a new objective-policy version and a new execution identity. It cannot be changed retroactively after benchmark outputs are inspected.

---

# Benchmark Protocol

## Research question

Can the bounded core reproduce its declared semantics and, after that, materially improve selected resource-constrained and operationally constrained schedules compared with serious native and human baselines?

## Benchmark stages

### Stage 1 — Semantic micro-tests

- Corpus: 50 fixtures in `benchmarks/semantic/cases`
- Scale: 1–6 activities
- Purpose: exact reference semantics and native comparison preparation
- Pass: zero unexplained differences inside any claimed profile

### Stage 2 — Algorithm sanity

- Corpus: PSPLIB J30, J60, J90 and J120
- Purpose: verify solver modelling and known objective values where available
- Limitation: no professional-scale or native-semantic conclusion may be drawn

### Stage 3 — Synthetic professional RCPSP

- Scale: 100–2,000 activities
- Include: several resources, calendars, priorities, frozen horizon and perturbations
- Comparators: unlevelled, default native, expert native, planner, optimiser, optimiser plus planner

### Stage 4 — Rich operational constraints

- Scale: 100–2,000 activities
- Include: named crews/equipment, skills, workfaces, permit windows, SIMOPS, modes and mobilisation
- Charge the optimiser for all data preparation and maintenance effort

### Stage 5 — Real anonymised schedules

- Initial: at least three schedules of roughly 500–2,000 activities
- Expansion: 5,000–10,000 only after earlier gates pass
- Enterprise stress: 25,000–50,000 only through a separately approved scale/decomposition protocol

### Stage 6 — Perturbation and stability

For each case, alter one factor at a time:

- delayed activity
- remaining duration
- actual start/finish
- unavailable crew/equipment
- permit window
- emergent activity
- relationship/lag
- shift calendar
- milestone priority

Measure activities moved, movement hours, frozen-horizon changes, resource reassignment and critical-path churn.

### Stage 7 — Determinism

- repeated same-process runs
- process restart
- clean environment
- separate supported machine
- serial versus later parallel profile
- exact input/output/explanation hash comparison

### Stage 8 — Native round-trip

1. Import native schedule.
2. Canonicalise and hash.
3. Produce proposed scenario.
4. Export through controlled adapter.
5. Reopen in native application.
6. Recalculate.
7. Re-import.
8. Diff all claimed fields and dates.
9. Reject silent material difference.

## Metrics

Keep separate:

- semantic correctness
- hard violations
- project completion
- milestone lateness
- resource peaks/overload/overtime
- stability and frozen-horizon movement
- continuity and mobilisation
- model preparation and review time
- runtime, memory, bounds and gaps
- explanation completeness
- native interchange loss
- practitioner acceptance
- buyer outcome

## Result labels

- `executed_pass`
- `executed_fail`
- `executed_inconclusive`
- `not_executed`
- `not_accessible`
- `native_validation_required`
- `practitioner_validation_required`
- `buyer_validation_required`

No proposed result may be promoted to `executed_*` without saved evidence and hashes.

---

# Comparator Protocol

## Required outputs for each resource-loaded case

A. Unlevelled CPM  
B. Native default levelling  
C. Native expert-configured levelling  
D. Experienced planner manual/selective solution  
E. Deterministic optimiser  
F. Optimiser reviewed and modified by planner

The principal comparison is `E versus C and D`, not `E versus B`.

## Native run record

Record before every native calculation:

- product name, edition, version and build
- operating system
- file hash before run
- project/calendar/status settings
- relationship-lag policy
- progress/out-of-sequence policy
- levelling mode
- levelling order/priority fields
- slack/float restrictions
- splitting options
- resource calendars and capacities
- activity/task priorities
- start/data/status date
- manual edits after levelling
- file hash after save
- reopen and recalculate result

## Expert-configured baseline

An expert baseline must be prepared or reviewed by a practitioner who regularly uses that product and relevant scheduling environment. The settings and manual changes must be logged. “Expert” cannot mean only selecting a non-default menu option without justification.

## Planner baseline

The planner receives the same scope, durations, logic, calendars, resources and operational facts. Record:

- elapsed working time
- assumptions added
- constraints absent from source data
- manual sequence changes
- rejected alternatives
- final rationale

## Blind review

Where possible, reviewers receive unlabeled schedules. Ranking and acceptance are frozen before source identity is revealed.

## Fairness controls

- identical input facts
- no hidden constraints supplied only to the optimiser
- all additional optimiser data separately timed and costed
- no default-only incumbent comparison
- no selective publication of favourable cases
- failed and timed-out optimiser runs retained
- planner modifications retained as evidence rather than treated as noise

---

# Data Access, Security and Anonymisation Plan

## Access required before decisive experiments

| Asset | Current Phase 0 status | Required action |
|---|---|---|
| Microsoft Project desktop | Not verified in this bundle | Record edition/version/build and establish repeatable native test machine |
| Primavera P6 | Not verified | Obtain lawful test access before any P6 compatibility claim |
| OR-Tools CP-SAT | Candidate selected; version unpinned | Pin exact release and package hash before first optimiser result |
| IBM CP Optimizer | Optional comparator; access/licence unverified | Confirm development and benchmark entitlement |
| PSPLIB | Dataset not bundled | Obtain from authoritative source and retain provenance/hash |
| Real schedules | None supplied to Phase 0 | Recruit at least three anonymised 500–2,000-activity cases |
| 5k–10k schedules | None | Seek only after earlier gates pass |
| Practitioners | None recruited | Recruit independent native-tool users for blind review |
| Buyers | None recruited | Interview separately after measured workflow evidence exists |

## Minimum real-schedule metadata

- source product and version
- activity and relationship count
- calendars
- status/data date
- actual-progress state
- resources and assignments
- baseline availability
- whether resource-loaded
- operational constraints available
- owner/contractor context
- project phase
- anonymisation method

## Anonymisation

Remove or transform:

- project/client/contractor names
- people and usernames
- site and asset identifiers
- financial values unless needed and approved
- document references
- proprietary codes
- free-text notes containing sensitive information

Preserve:

- network topology
- durations and relative dates where permitted
- calendar structure
- resource conflicts
- constraint semantics
- objective-relevant distinctions
- source-system field types

Date shifting must use one consistent offset per schedule so that durations, logic and status relationships remain intact.

## Handling rules

- keep original data outside the public repository;
- store only anonymised test fixtures in the benchmark corpus;
- hash every source and derived file;
- retain transformation scripts and logs;
- do not upload customer schedules to third-party AI services without explicit authorisation;
- use synthetic cases when contractual restrictions prevent sharing.

## Input-economics logging

Every real or rich-constraint case must record time spent on cleaning, mapping, constraint entry, review, export validation and planner correction using `registers/input-economics-log.csv`.

---

# Decision Gates and Stop Conditions

## Gates

### Semantic gate

Every claimed reference or native semantic must have zero unexplained discrepancies. A deliberate difference must be named, versioned and documented.

### Feasibility gate

Every released optimiser scenario must have zero hard temporal, resource, calendar, safety and operational violations under the independent validator.

### Superiority gate

Material improvement must be demonstrated across multiple independent cases against expert-configured native levelling and experienced planners. Default levelling alone is insufficient.

### Determinism gate

The same execution identity must produce exact schedule-hash and explanation-hash equality on every repeated run inside the declared boundary.

### Stability gate

Small perturbations must not cause operationally unacceptable unnecessary movement, especially within the frozen horizon.

### Explainability gate

Every consequential movement requires a structured, recomputable governing cause, objective consequence and counterfactual test path.

### Input-economics gate

Constraint capture, cleaning, maintenance, review and round-trip effort must be materially lower than the realised value generated.

### Interoperability gate

Representative native schedules must round-trip without silent material semantic loss in the claimed subset.

### Practitioner gate

Experienced practitioners must accept or constructively modify a meaningful portion of recommendations and be able to challenge the reasons.

### Buyer gate

A real budget-holding stakeholder must be willing to sponsor a measurable pilot.

### Competitive gate

The combined value must remain differentiated after serious comparison with current optimisation and scheduling products.

### Coherence gate

The initial capability must create stand-alone value without requiring a complete project-management suite.

## Stop or narrow conditions

- persistent unexplained P6/MSP semantic mismatch;
- no material advantage over expert-configured native levelling;
- no material advantage over experienced planner solutions;
- planner rejection for valid constraints absent from the model;
- model preparation consumes the realised benefit;
- small changes cause excessive churn;
- native round-trip changes the approved scenario materially;
- realistic 5k–10k cases cannot produce useful results in acceptable operational time;
- 25k–50k cases remain intractable after bounded decomposition;
- a competitor demonstrably matches the target combined contract;
- blind practitioner preference does not improve;
- no buyer will sponsor a measured pilot.

## Escalation condition

A production-product discussion is permitted only after semantic, feasibility, superiority, determinism, stability, explainability, input-economics, interoperability, practitioner and buyer gates have all produced positive evidence for a defined target segment.

---

# Phase 0 Change Control

## Freeze rule

The protocol is frozen at `phase0-0.1.0` before scheduling results exist.

Any change to semantics, objective levels, tie-breaking, comparator settings, metrics, case inputs, expected outputs, pass criteria or exclusions must:

1. receive a new version;
2. state the reason;
3. identify whether results already existed when the change was proposed;
4. list affected cases and prior outputs;
5. preserve the superseded version;
6. regenerate the manifest;
7. never overwrite unfavourable evidence.

## Change classes

- `editorial`: no semantic or benchmark effect;
- `clarification`: resolves ambiguity without changing expected result;
- `semantic`: changes calculation meaning;
- `benchmark`: changes case, comparator or metric;
- `deterministic`: changes execution identity or canonicalisation;
- `scope`: changes included or excluded capability.

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

---

# Phase 1 Entry Plan

## Phase 1 objective

Implement and test the declared reference semantic subset. Do not implement the optimiser first.

## Work packages

### WP1 — Repository and runtime pin

- choose implementation language/runtime;
- pin runtime and dependency versions;
- record platform fingerprint;
- adopt canonical JSON and SHA-256 implementation;
- set CI to run fixture/schema validation.

### WP2 — Canonical loader

- parse canonical schedule fixtures;
- reject duplicate IDs and unresolved references;
- expand explicit working intervals;
- preserve source-specific fields without interpreting them.

### WP3 — Reference CPM kernel

- activity-calendar duration arithmetic;
- FS, SS, FF, SF;
- signed lag;
- milestones;
- included constraints;
- restricted actual/status policies;
- restricted float calculation.

### WP4 — Independent validator

- relationship satisfaction;
- duration/calendar satisfaction;
- resource capacity where declared;
- immutable actuals;
- expected assertion comparison;
- deterministic serialisation and hash.

### WP5 — Run 50 semantic fixtures

- save one execution record per case;
- retain all failures;
- do not modify expected outputs without change control.

### WP6 — First native comparison

Microsoft Project is the practical first comparator only if lawful local access exists. Record exact version/settings, create native equivalents of selected microcases, reopen/recalculate and populate the compatibility matrix.

## Phase 1 exit criteria

- all 50 reference fixtures structurally and semantically executed;
- zero unexplained reference-profile discrepancies;
- deterministic hash equality across repeated runs;
- native test evidence clearly separated from untested profiles;
- no optimiser or product claim made from reference tests alone.
