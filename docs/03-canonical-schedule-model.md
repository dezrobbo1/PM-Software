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
