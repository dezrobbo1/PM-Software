# Canonical Schedule Model

## Design principles

- Neutral representation first; native adapters are explicit transformations.
- Source-specific state is preserved rather than silently normalised away.
- Historical facts, approved forecast and proposed scenario are distinct.
- Every calculation is tied to an immutable source snapshot and versioned policy.
- Unsupported native semantics remain labelled and preserved where possible.
- Stable identifiers are unique within their declared scope and all references must resolve.

The machine-readable schema is `schemas/canonical-schedule.schema.json`. The existing 50 Phase 0 fixtures remain canonical schema version `0.1.0`; Phase 0 release `0.1.2` expands and tightens the schema without changing their declared expected results.

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

Start and finish milestones have zero duration. Their remaining duration must be zero or null.

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

Each constraint has a stable ID, hard/soft classification, referenced activities/resources, applicable window/state and structured parameters. Referenced activities and resources must resolve.

### Baseline and approved forecast

A baseline or approved forecast is an immutable schedule-state record containing:

- stable state ID and a container-matching state type (`baseline` or `approved_forecast`);
- source snapshot and creation timestamp where available;
- one state record per represented activity;
- start, finish, remaining duration, selected mode and assignments;
- preserved source fields.

This separate approved-forecast state is required to calculate objective level 4, movement from the approved forecast.

### Proposed scenario

A proposed scenario contains:

- stable scenario ID;
- lifecycle status;
- objective-policy ID and complete objective vector;
- proposed activity states;
- alternative scenario IDs;
- governance and preserved source fields.

A proposed scenario remains non-authoritative until accepted under the authority boundary.

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

- unique calendar, resource, activity, relationship, WBS, operational-constraint and per-activity mode IDs;
- resolved calendar, WBS, resource, relationship, operational-constraint and scenario-state references;
- half-open calendar intervals in canonical ascending order;
- `0 <= start < finish <= horizon` for every working interval;
- no overlapping working intervals;
- complete expected activity times for every declared semantic fixture;
- RFC 3339 date-time validation, including a timezone offset;
- resolved resource assignments in baseline, approved-forecast and proposed-scenario activity states;
- state start/finish ordering and horizon bounds;
- context-correct baseline and approved-forecast state types;
- explicit, ordered coordinates for every frozen activity;
- the complete frozen register-file set.

## Native mapping policy

Every mapped field is classified as:

- `lossless`
- `transformed_equivalent`
- `transformed_material_difference`
- `unsupported_preserved`
- `unsupported_lost`
- `manual_approval_required`

Successful file import is not treated as semantic equivalence.
