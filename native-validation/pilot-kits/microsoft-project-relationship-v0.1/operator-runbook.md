# Microsoft Project relationship pilot operator runbook

Pilot: `microsoft-project-relationship-v0.1`

Status: `prepared_not_executed`

Cases: `SEM-REL-001` through `SEM-REL-012`

This kit prepares a partial 12-case pilot. It contains no native calculation,
adapter execution, compatibility result, production round-trip result, or
optimizer result. The 45-case gate is false.

The frozen repository contract governs claims. Official Microsoft documentation
and SDK material are the primary mapping references, but do not prove runtime
semantics. Only controlled execution on the captured, identified Project build
can establish observed native behavior.

## Before any track

Use only the files inventoried by `pilot-kit-manifest.json`; do not use an
unrestricted repository checkout as the operator packet. Verify the raw
preregistration, comparison-profile, and source-only case projection hashes in
`pilot-index.json`. The operator packet contains no expected-result path or
digest. Copy the selected file under
`tracks/manual_native_semantic_parity/environment-capture-templates/`,
`post-execution-attestation-template.json`, and the selected case sheets into
the ignored controlled execution workspace. Copy the matching Track A or Track
B `post-execution-action-log-template.json`; no adapter template exists while
Track C remains blocked. Keep `native-attempt-stop-record-template.json`
available as non-record instructions if a mandatory stop condition occurs.
Extract only the per-case
template's `capture` object into `environment.json`; the freeze and analyser
accept canonical JSON containing those capture fields, not the surrounding
template metadata. Complete every required placeholder except `status_date`,
which must remain null; complete the displayed progress-setting list, the exact
six-action log, observed ID/Unique ID/name fields, calendar and leveling
attestations, and every `observed_product_settings` observation before freeze.
Values under `required_value` and other prefilled mapping fields are plans, not
observations: fill `observed_value`, operator/reviewer IDs, and both RFC 3339
times from the native UI and independent evidence.
Complete the attestation copy only after real desktop execution.
Never edit the tracked deterministic kit. This is a procedural blind, not an
access-controlled blind: the public repository necessarily contains frozen
oracle-bearing fixtures and comparison controls. The operator packet excludes
those materials, and the operator and pre-execution reviewer must attest that
they did not inspect them before the native observation was frozen. A separate
comparison role releases the control only after the native artifacts and
normalized observation have been durably frozen and hashed.

Required capture fields (placeholder null is incomplete except for the required
null `status_date`):

- [ ] `product_name`
- [ ] `edition`
- [ ] `version`
- [ ] `build`
- [ ] `operating_system`
- [ ] `machine_architecture`
- [ ] `machine_time_zone`
- [ ] `locale`
- [ ] `execution_operator_id`
- [ ] `independent_reviewer_id`
- [ ] `native_file_format`
- [ ] `native_file_hashes_by_stage`
- [ ] `Microsoft_Project_project_calendar_and_scheduling_options`
- [ ] `Microsoft_Project_task_calendars`
- [ ] `Microsoft_Project_resource_calendars_and_capacities`
- [ ] `Microsoft_Project_task_scheduling_mode_type_and_effort_driven_fields`
- [ ] `Microsoft_Project_relationship_and_lag_settings`
- [ ] `Microsoft_Project_constraint_settings`
- [ ] `Microsoft_Project_project_start_and_status_date`
- [ ] `Microsoft_Project_calculation_and_progress_rescheduling_options`
- [ ] `Microsoft_Project_leveling_disabled_attestation`
- [ ] `manual_actions_by_stage`
- [ ] `native_source_file_format`
- [ ] `native_source_file_sha256`
- [ ] `project_calendar_settings`
- [ ] `task_calendar_per_task`
- [ ] `resource_calendar_and_capacity_per_assignment`
- [ ] `task_scheduling_mode_per_task`
- [ ] `task_type_per_task`
- [ ] `effort_driven_per_task`
- [ ] `relationship_and_lag_settings`
- [ ] `constraint_settings`
- [ ] `project_start`
- [ ] `status_date`
- [ ] `calculation_mode`
- [ ] `progress_rescheduling_options`
- [ ] `resource_leveling_status`
- [ ] `manual_construction_actions`
- [ ] `observed_native_activity_mapping`
- [ ] `observed_product_settings`
- [ ] `schedule_from_start`
- [ ] `precalculation_protocol_state`
- [ ] `manual_action_log_complete_attestation`
- [ ] `independent_verification_artifact_plan`

`manual_actions_by_stage` and `manual_construction_actions` must be identical
ordered arrays using the six action IDs in the per-case template. Fill each
`performed_by` and RFC 3339 `performed_at`; attest completeness. The evidence
plan must retain exactly these roles: `task_table`, `project_information`,
`calendar_working_time`, `predecessor_details`, `task_mode_type_effort`, and
`resource_leveling_status`. Record every native progress-rescheduling option
displayed by the tested build as a `setting_name`/`displayed_value` entry and
attest the list is complete. Do not substitute `{}` for a capture.

## Post-execution action log and evidence hashes

The canonical JSON file supplied with `--post-execution-action-log` must have
exactly these top-level fields: `schema_version` (value
`microsoft-project-post-execution-action-log-v0.1`), `pilot_id`,
`native_system` (value `microsoft_project`), `case_id`, `execution_track_id`,
`executed_at`, `operator_id`, `environment_capture_sha256`,
`case_realization_manifest_sha256`,
`complete_manual_action_log_attestation`, and `actions`. Bind its identities,
hashes, operator, and execution time to the exact analysis invocation and set
the completeness attestation to true only after the log is complete.

Every `actions` entry must contain exactly `sequence`, `action_id`, `action`,
`performed_at`, `stage_artifact_roles`, and `independent_evidence_roles`. Keep
the exact ordered action IDs from the selected generated template, use
contiguous one-based sequence numbers, and use RFC 3339 action times. Across
all entries, the
stage-role union must equal the exact track-stage roles supplied on the command
line and the evidence-role union must equal all six roles frozen in the
environment. Empty per-entry role arrays are permitted; missing, duplicate,
unknown, or incomplete role coverage is not.

After the action log, stage files, and independent-evidence files are final,
hash their raw bytes. Complete the attestation copy with those exact values in
`post_execution_action_log_sha256`, `stage_artifact_sha256_by_role`, and
`independent_evidence_artifact_sha256_by_role`. The analyser recomputes all
three domains and rejects a mismatch; the same file may not satisfy two roles.

## Track A — manual native semantic parity

1. Use only the matching manual build sheet and its raw-bound source facts.
2. Select Microsoft Project's built-in **24 Hours** calendar for `CAL-24X7`.
   Verify all seven days and no nonworking time in the native UI.
3. Disable resource leveling and do not run it. Set Microsoft Project's
   application calculation mode to **Manual**, schedule from the project start
   date, and do not invoke Calculate Project. Keep tasks automatically
   scheduled, fixed duration, not effort driven, with Manual=0 and Pinned=0.
4. In Project Information, set Start Date exactly to
   `2026-01-05T08:00:00+08:00` (local `Australia/Perth` wall time), then enter
   the tasks in mapped A-then-B order and explicit `4h`/`3h` durations. Display
   ID and Unique ID columns and verify the resulting values; Project UIDs are
   observed identifiers, not operator-assigned inputs.
5. Enter the source SNET constraints, relationship type, and signed lag.
   Independently verify the displayed fields.
6. Capture the task table, Project Information, calendar working-time view,
   predecessor details, task mode/type/effort fields, and leveling status as
   screenshots or native reports for independent verification. Complete every
   `observed_product_settings` record from those artifacts; do not copy its
   prefilled `required_value` into `observed_value` without observing it.
7. Freeze the case-realization record, environment capture, action log, and
   native source-file hash before the controlled native calculation.
8. Only after every manifest for the tracks being executed is frozen, run Project's controlled
   calculation, save the calculated native file, and hash it without editing.
9. Export the observed schedule as Project 2010 MSPDI XML (`SaveVersion=14`),
   hash it, and stop as inconclusive if that exact dialect is unavailable.
10. Complete the post-execution action log, freeze all six independent-evidence
    artifacts and the required track-stage artifacts, then hash-bind them in the
    post-execution attestation and run the analyser. The analyser releases its
    procedurally withheld comparison material only after the normalized native
    observation is durably written and hash-verified. On Windows it uses an
    exclusive write-through handle plus FlushFileBuffers; on POSIX it fsyncs the
    file and containing directory.
11. Preserve the analyser bundle and submit it, the screenshots/reports, and
    raw controlled artifacts for independent post-execution review.

This track may not use reopen evidence or adapter evidence as a substitute.

Example Track A freeze (replace every angle-bracketed value):

```text
python -m deterministic_scheduling_core freeze-msproject-native-input \
  --pilot microsoft-project-relationship-v0.1 \
  --case SEM-REL-001 \
  --track manual_native_semantic_parity \
  --native-file <controlled-workspace>/SEM-REL-001-source.mpp \
  --environment-capture <controlled-workspace>/SEM-REL-001-environment.json \
  --output-dir <controlled-workspace>/SEM-REL-001-track-a-freeze \
  --prepared-at <RFC3339-time> \
  --prepared-by <operator-id> \
  --independent-pre-execution-reviewed-by <reviewer-id> \
  --attest-no-native-result-observed-before-freeze
```

Example Track A analysis after actual native calculation and evidence freeze:

```text
python -m deterministic_scheduling_core analyse-msproject-native-output \
  --pilot microsoft-project-relationship-v0.1 \
  --case SEM-REL-001 \
  --track manual_native_semantic_parity \
  --native-output <controlled-workspace>/SEM-REL-001-observed-project-2010.xml \
  --case-realisation-manifest <controlled-workspace>/SEM-REL-001-track-a-freeze/case-realisation-manifest.json \
  --environment-capture <controlled-workspace>/SEM-REL-001-environment.json \
  --post-execution-attestation <controlled-workspace>/SEM-REL-001-track-a-attestation.json \
  --post-execution-action-log <controlled-workspace>/SEM-REL-001-track-a-action-log.json \
  --evidence-artifact task_table=<controlled-workspace>/track-a-task-table.png \
  --evidence-artifact project_information=<controlled-workspace>/track-a-project-information.png \
  --evidence-artifact calendar_working_time=<controlled-workspace>/track-a-calendar-working-time.png \
  --evidence-artifact predecessor_details=<controlled-workspace>/track-a-predecessor-details.png \
  --evidence-artifact task_mode_type_effort=<controlled-workspace>/track-a-task-mode-type-effort.png \
  --evidence-artifact resource_leveling_status=<controlled-workspace>/track-a-resource-leveling-status.png \
  --stage-artifact native_calculated_file_sha256=<controlled-workspace>/SEM-REL-001-calculated.mpp \
  --output-dir <controlled-workspace>/SEM-REL-001-track-a-analysis \
  --run-id <stable-run-id> \
  --executed-at <RFC3339-time>
```

The value after each `--stage-artifact ROLE=` and
`--evidence-artifact ROLE=` is a file path; the analyser computes and
records its SHA-256. It is not a caller-supplied digest. Track A's action-log
stage-role union is exactly `native_calculated_file_sha256`; its evidence-role
union is exactly the six roles shown above.

## Track B — saved-file reopen/recalculate stability

1. Before the first calculation, freeze a separate Track B manifest bound to
   the same source file and the already frozen Track A manifest.
2. Start only from that exact dual-frozen realization.
3. Hash the native pre-close file and normalized pre-close observation.
4. Save, close, and reopen without editing; hash the reopened file.
5. Recalculate without leveling or manual intervention, then hash the
   recalculated file and normalized post-recalculation observation.
6. Submit the separate reopen evidence for independent review.

This track can test stability only. It cannot satisfy the native-semantic or
adapter-interchange track. Track B compares only its independently normalized
pre-close and post-recalculation observations and has no comparison-control
access.

Example Track B freeze, using the same native source and exact environment file:

```text
python -m deterministic_scheduling_core freeze-msproject-native-input \
  --pilot microsoft-project-relationship-v0.1 \
  --case SEM-REL-001 \
  --track saved_file_reopen_recalculate_stability \
  --native-file <controlled-workspace>/SEM-REL-001-source.mpp \
  --environment-capture <controlled-workspace>/SEM-REL-001-environment.json \
  --prerequisite-manual-case-realization-manifest <controlled-workspace>/SEM-REL-001-track-a-freeze/case-realisation-manifest.json \
  --output-dir <controlled-workspace>/SEM-REL-001-track-b-freeze \
  --prepared-at <RFC3339-time> \
  --prepared-by <operator-id> \
  --independent-pre-execution-reviewed-by <reviewer-id> \
  --attest-no-native-result-observed-before-freeze
```

Example Track B analysis requires exactly these five separate stage files:

```text
python -m deterministic_scheduling_core analyse-msproject-native-output \
  --pilot microsoft-project-relationship-v0.1 \
  --case SEM-REL-001 \
  --track saved_file_reopen_recalculate_stability \
  --native-output <controlled-workspace>/SEM-REL-001-post-recalculate.xml \
  --case-realisation-manifest <controlled-workspace>/SEM-REL-001-track-b-freeze/case-realisation-manifest.json \
  --prerequisite-manual-case-realization-manifest <controlled-workspace>/SEM-REL-001-track-a-freeze/case-realisation-manifest.json \
  --environment-capture <controlled-workspace>/SEM-REL-001-environment.json \
  --post-execution-attestation <controlled-workspace>/SEM-REL-001-track-b-attestation.json \
  --post-execution-action-log <controlled-workspace>/SEM-REL-001-track-b-action-log.json \
  --evidence-artifact task_table=<controlled-workspace>/track-b-task-table.png \
  --evidence-artifact project_information=<controlled-workspace>/track-b-project-information.png \
  --evidence-artifact calendar_working_time=<controlled-workspace>/track-b-calendar-working-time.png \
  --evidence-artifact predecessor_details=<controlled-workspace>/track-b-predecessor-details.png \
  --evidence-artifact task_mode_type_effort=<controlled-workspace>/track-b-task-mode-type-effort.png \
  --evidence-artifact resource_leveling_status=<controlled-workspace>/track-b-resource-leveling-status.png \
  --stage-artifact native_pre_close_file_sha256=<controlled-workspace>/SEM-REL-001-pre-close.mpp \
  --stage-artifact native_pre_close_output_sha256=<controlled-workspace>/SEM-REL-001-pre-close.xml \
  --stage-artifact native_reopened_file_sha256=<controlled-workspace>/SEM-REL-001-reopened.mpp \
  --stage-artifact native_recalculated_file_sha256=<controlled-workspace>/SEM-REL-001-recalculated.mpp \
  --stage-artifact native_post_recalculate_output_sha256=<controlled-workspace>/SEM-REL-001-post-recalculate.xml \
  --output-dir <controlled-workspace>/SEM-REL-001-track-b-analysis \
  --run-id <stable-run-id> \
  --executed-at <RFC3339-time>
```

Track B's action-log stage-role union is exactly the five stage roles in this
example; its evidence-role union is a separate Track B realization of the same
six planned roles. Track A evidence files cannot be supplied as Track B
evidence merely to satisfy the role names. The analyser revalidates the full
prerequisite Track A manifest supplied above; this flag is required for Track B
and forbidden for Tracks A and C.

## Track C — MSPDI adapter interchange

`adapter_preparation_status` is `preparation_blocked` for every case. The
official reviewed sources do not normatively establish the exact `FromTime`
and `ToTime` serialization needed to preserve continuous `CAL-24X7` semantics.
Do not invent, generate, import, or manually transcribe an MSPDI input. Resume
only under an approved, versioned mapping decision.

This blocker is a preparation gap, not a native failure. It supplies no
adapter-interchange or compatibility claim.

## Mandatory stop conditions and outcomes

- Any silent raw-source or binding change: stop before execution, preserve the
  evidence, and require a new versioned decision. Do not classify a result.
- Any missing, late, changed, or discarded pre-execution realization record,
  or any calculation/recalculation observed before its freeze: record
  `executed_inconclusive`; never reconstruct or overwrite the evidence.
- Wrong or unverified task mode, task type, effort-driven setting, calendar,
  locale, time zone, or leveling disabled state: record
  `executed_inconclusive`. If leveling ran, stop and preserve the failed
  attempt's evidence; never reuse it as a conforming run.
- An export outside the reviewed Project 2010 MSPDI namespace or with
  `SaveVersion` other than 14: record `executed_inconclusive` and require a
  separately reviewed dialect mapping; do not assume a newer dialect is equal.
- A post-freeze native task-mode, relationship-type, relationship-lag, or
  claim-field transformation; an off-grid timestamp; an unapproved
  transformation; or an unregistered edit after calculation: record
  `executed_fail` under the frozen profile.
- Any inaccessible or incomplete required evidence leaves its gate open.

For every stopped attempt, use the dedicated recorder rather than inventing
missing stage hashes or forcing the normal analyser to accept an incomplete
bundle. The recorder rebinds the pilot, case, track, source-only projection,
registry-backed full-fixture digest, preregistration, and comparison profile;
hashes only artifacts that
actually exist; refuses to overwrite its output; and can never emit a native
run record, `executed_pass`, or claim-eligible evidence. Supply a valid frozen
manifest and its environment capture when they exist. Omit the manifest when a
late freeze means none exists, and list each actual remaining artifact with a
repeatable `--observed-artifact ROLE=PATH`. The generated
`native-attempt-stop-record-template.json` is an instruction document only,
not a stopped-attempt record.

Example for a native calculation observed before the pre-execution freeze:

```text
python -m deterministic_scheduling_core record-msproject-native-attempt-stop   --pilot microsoft-project-relationship-v0.1   --case SEM-REL-001   --track manual_native_semantic_parity   --stopped-at <RFC3339-time>   --recorded-by <operator-id>   --stop-condition native_calculation_occurred_before_preexecution_freeze   --reason <concise-stop-reason>   --outcome-classification executed_inconclusive   --native-calculation-observed   --environment-capture <controlled-workspace>/SEM-REL-001-environment.json   --observed-artifact native_file=<controlled-workspace>/SEM-REL-001-observed.mpp   --output-dir <controlled-workspace>/SEM-REL-001-stopped-attempt
```

The command applies the frozen stop-condition/outcome table. A condition found
before native calculation records `not_executed`; after calculation it records
only the condition's frozen `executed_inconclusive` or `executed_fail`
classification. Formal native claim ingestion remains unavailable for this
record and any retry requires a new frozen realization.

No status or artifact may cross-satisfy another track. Even completed work on
these 12 cases cannot satisfy the full 45-case gate or support full Microsoft
Project compatibility, MPP binary compatibility, safe production round-trip,
or optimizer superiority.
