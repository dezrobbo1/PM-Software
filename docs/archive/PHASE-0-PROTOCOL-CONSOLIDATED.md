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

# Reference Semantic Contract `reference-v0.3`

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

For `reference-v0.3`:

- lag is consumed only on the successor activity calendar;
- positive lag adds productive working time;
- negative lag subtracts productive working time;
- zero lag preserves the predecessor event coordinate;
- all activities are bounded by project start unless an actual start precedes it;
- when several bounds apply, the latest feasible start governs;
- for finish-based bounds, the activity start is derived by subtracting its productive duration on its calendar;
- for an in-progress successor under `retained_logic`, a start-governed relationship is tested against `remaining_start` when that coordinate exists;
- for an in-progress successor under `progress_override`, unfinished predecessor logic may be intentionally non-governing for remaining start, as declared by the profile.

The canonical schema can preserve a non-null `lag_calendar`, but the active executable profile rejects it. Alternate lag-calendar semantics require a new profile and a direct expected-result fixture before execution. P6 and Microsoft Project lag/calendar rules are not assumed equivalent and require separate native profiles.

## Constraints included in `reference-v0.3`

- `start_no_earlier_than`
- `finish_no_earlier_than`
- fixed actual start
- fixed actual finish
- frozen start/finish within a declared frozen horizon

The canonical model can preserve `fixed_start` and `fixed_finish` constraint records, but the executable reference profile does not claim those semantics because the frozen corpus contains no direct fixture for either type. They require a later profile and direct expected-result cases before execution.

## Profile history

- `reference-v0.1` is the original preregistered profile.
- `reference-v0.2` removed untested `fixed_start` and `fixed_finish` execution claims.
- `reference-v0.3` removes untested alternate lag-calendar and cumulative-capacity execution claims.

All superseded profiles remain in `config/` for auditability. No CPM, optimiser or native result existed when v0.3 was declared.

## Actuals and status

- Actual start and actual finish are immutable historical facts.
- A completed activity uses its actual start and actual finish.
- An in-progress activity retains actual start and schedules remaining work no earlier than the status time unless a declared policy allows otherwise.
- `retained_logic`: remaining successor work waits for unfinished predecessor work.
- `progress_override`: remaining successor work may continue from status time despite unfinished predecessor logic.
- `actual_dates`: included as a native-validation case only in Phase 0; no unsupported equivalence is invented.

## Resources

The active executable profile claims only capacity-one exclusive resources because that is the only resource-capacity semantic directly represented in the frozen corpus.

- An executable reference resource has type `exclusive` and capacity `1`.
- Activity demand must not exceed that exclusive capacity at any time.
- Resource calendar availability intersects with the activity calendar.
- Equal-quality choices are resolved by the declared objective policy and stable activity-ID tie-break.

The canonical schema may preserve renewable, cumulative and non-renewable resource records. Cumulative capacity greater than one is not executable under `reference-v0.3`; it requires a new profile and direct expected-result fixtures.

## Float for reference micro-tests

Float is calculated only for simple 24x7 acyclic networks without actuals, resource constraints or date constraints:

- project finish is the maximum early finish;
- backward pass starts from project finish;
- total float is `late_start - early_start`;
- free float is the minimum successor early start minus activity early finish, or project finish minus early finish for a terminal activity.

No claim is made that this restricted float profile matches every native product configuration.

## Declared reference-oracle validation

The 49 fixtures marked `declared` are exact reference assertions, not merely feasible examples. The independent validator recomputes the earliest canonical coordinates from the input network and compares every start, remaining-start, finish and project-finish coordinate exactly. `SEM-STA-045` remains excluded because its `actual_dates` result is deliberately native-validation-only.

The bounded oracle applies only the semantics exercised by the frozen corpus:

- completed activities preserve actual start and finish without substituting nominal duration;
- in-progress activities preserve actual start and consume remaining duration from a status-bounded remaining start;
- unstarted activities consume nominal duration on the intersection of the activity calendar and every mandatory assigned-resource calendar;
- SNET, FNET and all four relationship formulas contribute lower bounds, with lag consumed on the successor activity calendar;
- capacity-one exclusive demand is checked over productive half-open segments;
- the two contended-resource fixtures enumerate their two legal orders and use the frozen objective vector to select the canonical order; and
- the two float fixtures use only the restricted 24x7, acyclic, unconstrained FS-zero backward pass declared above.

`driving_relationships` is a preregistered curated assertion set, not a claim to enumerate every tight or critical relationship. The validator freezes each existing set and independently requires every listed relationship to attain the successor's governing coordinate after calendar adjustment. Defining a complete critical-path set would require a later amendment and direct fixture review.

## Unsupported or unresolved semantics

The following require later, separate profiles:

- explicit alternate relationship-lag calendars;
- cumulative or renewable resource-capacity semantics beyond one exclusive unit;
- P6 retained-logic, progress-override and actual-dates parity beyond declared cases;
- P6 relationship-lag calendar options;
- canonical `fixed_start` and `fixed_finish` execution semantics;
- Microsoft manual task scheduling;
- native duration-type semantics;
- resource-dependent activity/task types;
- summary and level-of-effort semantics;
- suspend/resume behaviour;
- multiple float paths;
- cross-project relationships;
- full constraint hierarchies.
- hard operational constraints and project required-finish execution in the reference oracle.

Any unexplained native difference is a failed compatibility claim, not a reason to modify the reference result after the fact.

---

# Canonical Schedule Model

## Design principles

- Neutral representation first; native adapters are explicit transformations.
- Source-specific state is preserved rather than silently normalised away.
- Historical facts, approved forecast and proposed scenario are distinct.
- Every supplied approved forecast and proposed scenario must exactly cover the canonical activity set; partial state is rejected.
- Every calculation is tied to an immutable source snapshot and versioned policy.
- Unsupported native semantics remain labelled and preserved where possible.
- Stable identifiers are unique within their declared scope and all references must resolve.

The machine-readable schema is `schemas/canonical-schedule.schema.json`, version `0.1.3`. All 50 Phase 0 fixtures have been migrated to that schema version. Their scheduling inputs and declared expected results remain unchanged.

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
- `project`
  - `project_start`
  - `status_time`
  - `required_finish`
  - `progress_policy`
  - optional `frozen_horizon_finish`
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

### WBS node

- stable `id`
- `name`
- optional `parent_id`
- optional canonical outline order
- preserved source fields

Parent references must resolve and the hierarchy must be acyclic, including multi-node cycles.

### Activity

- stable `id`
- `name`
- optional `wbs_id`
- `kind`: task, start milestone, finish milestone
- `duration`
- `remaining_duration`
- `calendar_id`
- `actual_start`
- `actual_finish`
- `constraints`
- `assignments`
- `eligible_modes`
- optional `frozen_state`
- milestone priority and due time where applicable
- preserved source fields

Every date constraint has a stable non-empty ID so that explanation records can resolve the governing constraint. Start and finish milestones have zero duration. Every eligible milestone mode also has zero duration. An `actual_finish` requires an `actual_start` and may not precede it. An in-progress activity—actual start present and actual finish absent—requires an explicit non-null remaining duration.

### Relationship

- stable `id`
- predecessor and successor IDs
- `type`: FS, SS, FF, SF
- signed lag
- optional explicit lag calendar
- preserved source-system representation

Every non-null lag-calendar reference must resolve to a declared calendar.

### Resource

- stable `id`
- optional name
- type: renewable, exclusive, cumulative, non-renewable
- capacity
- calendar
- skills and certifications
- location/work area
- preserved source-system reference

An `exclusive` resource has capacity exactly one. Availability is represented through its calendar rather than by changing exclusive capacity.

### Execution mode

An activity may declare zero or more eligible modes. A mode contains:

- stable mode ID within the activity;
- duration;
- optional calendar override;
- resource assignments;
- required skills;
- preserved mode parameters.

### Operational constraint

The schema can represent these bounded prototype classes:

- workface occupancy;
- permit/time window;
- isolation state;
- SIMOPS exclusion;
- material/release state;
- mandatory supervision;
- alternative mode;
- continuity/minimum run;
- mobilisation transition;
- frozen horizon;
- explicitly preserved custom state.

Each constraint has a stable ID, hard/soft classification, referenced activities/resources, applicable window/state and structured parameters. Referenced activities and resources must resolve. Every supplied time window is ordered and lies within the schedule horizon.

### Baseline and approved forecast

A baseline or approved forecast is an immutable schedule-state record containing:

- stable state ID and a container-matching state type (`baseline` or `approved_forecast`);
- source snapshot and creation timestamp where available;
- represented activity states;
- start, finish, remaining duration, selected mode and assignments;
- preserved source fields.

For an ordinary unstarted activity, each saved state span must consume its selected activity/mode duration over the selected activity and resource calendars. A state cannot claim arbitrary start and finish coordinates inconsistent with its own canonical inputs.

### Proposed scenario

A proposed scenario contains:

- stable scenario ID;
- lifecycle status;
- active objective-policy ID and complete case-specific objective vector;
- one proposed state for every schedule activity;
- alternative scenario IDs;
- governance and preserved source fields.

A proposed scenario remains non-authoritative until accepted under the authority boundary. An approved or rejected scenario requires matching governance state, decision ID, actor and timestamp.

### Governance

Governance can record:

- approval state;
- decision ID;
- rationale;
- hashed evidence references;
- actor and timestamp;
- source system;
- model, calculation and objective-policy versions;
- rejected alternatives.

## Canonical validation rules

The Phase 0 validator enforces rules that JSON Schema cannot express reliably by itself:

- all semantic fixtures use canonical schema `0.1.3` and resolve to the exact frozen active `reference-v0.3` profile;
- unique calendar, resource, activity, relationship, date-constraint, WBS, operational-constraint and per-activity mode IDs;
- resolved calendar, WBS, resource, relationship, operational-constraint and scenario-state references;
- acyclic WBS parent hierarchy;
- half-open calendar intervals in canonical ascending order;
- `0 <= start < finish <= horizon` for every working interval;
- no overlapping working intervals;
- complete expected activity times for every declared semantic fixture;
- expected coordinates, milestones and project finish within the declared horizon;
- zero expected span for milestones;
- RFC 3339 date-time validation, including a timezone offset;
- valid actual-start/actual-finish ordering, explicit remaining duration and an in-horizon status time not earlier than any in-progress actual start;
- resolved resource assignments in baseline, approved-forecast and proposed-scenario activity states;
- state start/finish ordering, horizon bounds and duration/calendar satisfaction for unstarted work;
- context-correct baseline and approved-forecast state types;
- complete approved-forecast activity coverage;
- complete proposed-scenario activity coverage, preservation of every frozen coordinate and active objective-vector shape;
- ordered, in-horizon operational windows;
- explicit, ordered coordinates for every frozen activity;
- exact fixture/catalogue metadata agreement;
- exact frozen filename and header sequence for every evidence register;
- the complete authoritative protocol chapter set.

`fixed_start` and `fixed_finish` remain representable as preserved canonical source state, but they are not executable under `reference-v0.3` until direct semantic fixtures and expected results are approved.

## Native mapping policy

Every mapped field is classified as:

- `lossless`
- `transformed_equivalent`
- `transformed_material_difference`
- `unsupported_preserved`
- `unsupported_lost`
- `manual_approval_required`

Successful file import is not treated as semantic equivalence.

---

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

The machine-readable contract is `schemas/execution-record.schema.json`, schema revision `0.1.4`. Every record contains the following fields, even where their value is null or `not_applicable`:

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

An optimal or feasible-not-proven result must be feasible. An optimal result has absolute optimality gap exactly `0`. A proven-infeasible result must be classified infeasible, must have a null selected-scenario hash, must carry an empty objective vector, and must have null best-bound and optimality-gap values. Its output and explanation hashes may identify proof evidence, but they must not identify a feasible selected schedule. A non-optimisation semantic execution may remain `not_applicable` for feasibility and optimality and uses an empty objective vector.

The cross-validator derives the complete objective-vector length from the case's mandatory milestone groups, activities, modes and resources, then recomputes every value from a complete, feasible selected activity-state set. Shape alone is insufficient. Every non-empty execution objective vector is recomputed, including one retained with an `unknown` optimality classification. Feasible optimisation evidence without complete selected states fails closed; non-optimisation semantic executions remain `not_applicable` with an empty vector.

For a standalone execution record, the validator caller must load the complete selected activity states from the immutable artifact identified by the selected-scenario hash and supply them for recomputation. The execution-record schema does not duplicate that output artifact. A missing artifact is not treated as proof of a vector's values.

The same evidence binding applies to an optimisation explanation: its selected states are loaded by the explanation output hash, not inferred from an unrelated in-memory scenario. The active value-recomputation guard covers unstarted complete-state outputs in the current executable profile; actual/progress output-state objective recomputation remains fail-closed until a separately reviewed output profile exists.

A failed or inconclusive execution may lack a selected scenario when failure occurred before one was produced, but the immutable failure evidence bundle remains mandatory.

Non-executed result labels must not contain an input, execution, output, selected-scenario, explanation or evidence-bundle hash and must not claim that validation ran. `native_validation_required` must explicitly record a native round-trip status of `required_not_run`.

## Counterfactual execution evidence

A counterfactual is a separate recomputation, not narrative inference. A feasible counterfactual must contain a validated output hash, a non-empty objective vector and validator status `pass`. A proven-infeasible counterfactual records no output schedule, an empty objective vector and validator status `pass`. An unknown result cannot claim an output or objective vector. The changed input, execution identity, result evidence hash and evidence paths remain mandatory.

Counterfactual input changes use non-empty RFC 6901 JSON Pointer paths. Only `~0` and `~1` are valid escape sequences; malformed pointers are rejected before any recomputation is accepted.

For a feasible counterfactual, semantic validation applies the declared patch to a copy of the canonical input and loads the complete counterfactual states associated with its output hash. It then revalidates feasibility and recomputes the full objective vector against the patched input. The immutable approved forecast and existing proposed-output state cannot be patched. A focus-activity coordinate pair or output hash alone is insufficient.

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

---

# Benchmark Objective Policy `objective-v0.3`

This is a transparent experimental policy. It is not a validated universal planner preference.

`objective-v0.1` and `objective-v0.2` remain in `config/` as superseded preregistrations. Version 0.1 left equal-priority milestone aggregation ambiguous. Version 0.2 fixed that ambiguity but did not completely define the mandatory-milestone predicate, the combined level-five metric or the final case-specific vector shape. No benchmark result existed when `objective-v0.3` superseded them.

## Lexicographic levels

1. Zero hard safety, temporal, calendar, resource and operational violations.
2. Minimise mandatory milestone lateness using the exact priority-group rule below.
3. Minimise project completion time.
4. Minimise movement from the approved forecast.
5. Minimise the ordered operational-resource tuple: overtime units, mobilisation blocks, then summed resource peak demand.
6. Minimise continuity interruptions.
7. Resolve remaining equality through the complete canonical scenario-decision vector.

A lower level cannot improve at the expense of a higher level.

## Mandatory milestone definition

A mandatory milestone is an activity where all of the following hold:

- `kind` is `start_milestone` or `finish_milestone`;
- `milestone_priority > 0`;
- `due_time` is not null.

A normal task does not become a mandatory milestone merely because it has a priority and due time.

For each mandatory milestone `m`:

```text
lateness(m) = max(0, finish(m) - due_time(m))
```

All values are integers in the schedule's declared time unit.

## Exact priority-group aggregation

1. Group mandatory milestones by integer `milestone_priority`.
2. Evaluate groups in descending priority.
3. For one priority group, compare this tuple lexicographically:

```text
(
  sum of milestone lateness in the group,
  maximum individual milestone lateness in the group,
  individual lateness values ordered by stable ascending milestone ID
)
```

4. Advance to the next lower-priority group only when the complete tuple for the current group is equal.
5. Advance to project finish only when every priority-group tuple is equal.

This rule makes equal-priority outcomes reproducible. It does not claim that sum-first aggregation is a universal planner preference.

## Approved-forecast movement

For the same canonical input, objective level 4 is:

```text
sum over stable ascending activity IDs of:
  abs(proposed_start - approved_start)
  + abs(proposed_finish - approved_finish)
```

If the canonical input contains no approved forecast, the component is exactly `0`. If an approved forecast is supplied, it must contain exactly one resolved, valid state for every canonical activity; partial supplied forecasts cannot use the zero fallback. Competing scenarios are never permitted to add or remove the approved forecast; it belongs to the immutable input snapshot.

## Exact level-five tuple

Level 5 is not a weighted composite. It is compared lexicographically as:

```text
(
  overtime_units,
  mobilisation_block_count,
  resource_peak_demand_sum
)
```

For canonical schema `0.1.3`:

- `overtime_units` is fixed at `0` because overtime availability is not yet represented. Introducing non-zero overtime creates a new canonical-model and objective-policy version.
- `mobilisation_block_count` is the sum, across stable resource IDs, of maximal contiguous or overlapping productive assignment blocks.
- `resource_peak_demand_sum` is the sum, across stable resource IDs, of each resource's maximum concurrent integer assignment demand.

This ordering means one less overtime unit is preferred before mobilisation or peak demand; one less mobilisation block is preferred before peak demand.

## Continuity component

`continuity_interruption_count` is fixed at `0` under canonical schema `0.1.3` because split execution is not yet represented. It is retained as an explicit reserved component rather than an undefined prose penalty. Enabling split work or a non-zero continuity metric requires a new canonical-model and objective-policy version.

## Canonical tie-break vector

For every activity in stable ascending activity-ID order, append:

```text
start,
finish,
mode_ordinal,
assignment demand for every resource in stable ascending resource-ID order
```

`mode_ordinal` is `0` when no mode is selected. Otherwise it is one plus the selected mode's index in stable ascending mode-ID order. Missing resource assignments encode as `0`.

This is a vector, not an opaque integer rank. Its exact length depends on the canonical input.

## Complete objective-vector encoding

The canonical integer vector is flattened in this order:

```text
[
  hard_violation_count,
  for each mandatory-milestone priority group in descending order:
    group_sum_lateness,
    group_maximum_lateness,
    each individual lateness in stable ascending milestone-ID order,
  project_finish,
  approved_forecast_movement,
  overtime_units,
  mobilisation_block_count,
  resource_peak_demand_sum,
  continuity_interruption_count,
  for each activity in stable ascending activity-ID order:
    start,
    finish,
    mode_ordinal,
    each resource demand in stable ascending resource-ID order
]
```

The Phase 0 validator derives the required vector layout from the canonical schedule and rejects incomplete or surplus entries. It also recomputes every entry from complete feasible activity states, including mandatory-milestone lateness, project finish, approved-forecast movement, the explicit resource tuple and the stable activity/resource tie vector. A fixed seven-entry vector is invalid because levels 2 and 7 are deliberately case-specific vectors, and a correctly sized fabricated vector is also invalid.

The recomputed hard-violation component is `0` only after the selected states pass the active executable feasibility checks. Unsupported semantic branches or missing output states fail closed rather than inventing a positive violation-count convention.

Execution and explanation validators load complete states through evidence maps keyed by the claimed selected-scenario or output hash. They do not substitute an unbound proposed state. Every non-empty execution vector is recomputed even when optimality is `unknown`. Feasible counterfactual vectors are recomputed only after applying and validating their canonical-input patch; the approved forecast is immutable across competing scenarios.

## Required scenario comparison

For every candidate scenario, retain the full vector and separate metrics. Do not collapse quality, runtime, stability, modelling effort and practitioner acceptance into one composite score.

## Change control

Any change to level order, mandatory-milestone definition, aggregation, metric definition, reserved-component behaviour or tie-break creates a new objective-policy version and a new execution identity. It cannot be changed retroactively after benchmark outputs are inspected.

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

---

# Phase 1 Entry Plan

## Phase 1 objective

Implement and test the declared reference semantic subset. Do not implement the optimiser first.

## Mandatory entry checks

Before Phase 1 code is added:

```bash
python -m unittest discover -s tests -v
python tools/validate_phase0.py
```

Both commands must pass from a clean Git checkout. The manifest must exactly cover the tracked protocol files, and the consolidated protocol must match the numbered authoritative documents.

## Work packages

### WP1 — Repository and runtime pin

- choose implementation language/runtime;
- pin runtime and dependency versions;
- record platform fingerprint;
- adopt canonical JSON and SHA-256 implementation;
- keep CI running schema, negative-guard and manifest validation.

### WP2 — Canonical loader

- parse canonical schedule fixtures;
- reject duplicate IDs, unresolved references and WBS cycles;
- reject invalid, overlapping or out-of-horizon calendar intervals;
- expand explicit working intervals;
- preserve source-specific fields without interpreting them;
- represent baseline, approved forecast and proposed scenario separately;
- enforce complete coverage for every supplied approved forecast and proposed scenario, preservation of frozen coordinates and case-specific objective-vector shape;
- validate saved state spans against selected duration and calendar intersections.

### WP3 — Reference CPM kernel

- activity-calendar duration arithmetic;
- FS, SS, FF, SF;
- signed lag on the successor activity calendar;
- reject non-null explicit lag calendars from the active profile until a direct fixture exists;
- milestones;
- included constraints;
- reject preserved-only `fixed_start` and `fixed_finish` from the active `reference-v0.3` execution path until direct fixtures exist;
- restricted actual/status policies;
- restricted float calculation.

### WP4 — Independent validator

- relationship satisfaction;
- duration/calendar satisfaction;
- capacity-one exclusive resources; reject cumulative capacity from the active profile until a direct fixture exists;
- immutable actuals;
- require deterministic in-progress status time;
- expected assertion comparison;
- deterministic serialisation and hash;
- execution-record and explanation-schema validation;
- coordinate-derived movement checks, canonical cause resolution, RFC 6901 counterfactual patches and calculation-trace evidence;
- explicit native round-trip disposition and zero-gap proof for optimal results.

### WP5 — Run 50 semantic fixtures

- save one execution record per case;
- retain all failures;
- require complete evidence and hashes before using an `executed_*` label;
- do not modify expected outputs without change control.

### WP6 — First native comparison

Microsoft Project is the practical first comparator only if lawful local access exists. Record exact version/settings, create native equivalents of selected microcases, reopen/recalculate and populate the compatibility matrix.

## Phase 1 exit criteria

- all 50 reference fixtures structurally and semantically executed;
- zero unexplained reference-profile discrepancies;
- deterministic hash equality across repeated runs;
- native test evidence clearly separated from untested profiles;
- no optimiser or product claim made from reference tests alone.
