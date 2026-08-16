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
