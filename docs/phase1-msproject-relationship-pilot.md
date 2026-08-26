# Phase 1.1 Microsoft Project relationship pilot

Status: `prepared_not_executed`

Pilot ID: `microsoft-project-relationship-v0.1`

This pilot is a preparation artifact for `SEM-REL-001` through
`SEM-REL-012`. It does not record a Microsoft Project calculation, an MSPDI
round trip, save/reopen stability, or any compatibility result. The frozen
repository preregistration and comparison profile define the claim boundary;
official Microsoft documentation is used only to map that frozen contract to
Microsoft Project fields.

## Why twelve cases come first

The cases isolate FS, SS, FF and SF links at zero, positive and negative lag.
They are the smallest useful check of relationship and lag representation
before investing in the remaining network, calendar, constraint, status and
float cases. Even twelve future passes cannot satisfy any 45-case Microsoft
Project gate.

## Three evidence tracks remain independent

- `manual_native_semantic_parity` requires a manually constructed, reviewed
  native realization and can support only the bounded semantic subset.
- `saved_file_reopen_recalculate_stability` requires save, close, reopen and
  recalculation evidence from the same frozen realization and can support only
  the stability subset.
- `adapter_interchange_round_trip` requires a frozen MSPDI input and controlled
  export/re-import evidence. Manual transcription cannot support this track.

No artifact or result from one track substitutes for another.

## Oracle blinding

Each case has a deterministic `source-only-case-projections/` artifact containing
only the construction inputs needed by the operator and pre-execution reviewer.
The operator build sheet, review sheet, reopen protocol, adapter blocker and
pilot index bind that projection's bytes. None of those operator-visible
materials identifies or hash-binds the oracle-bearing semantic fixture.

The full frozen fixture path and raw hash remain bound only inside the matching
`sealed-expected-normalized/` artifact. That artifact stays unavailable to the
operator and pre-execution reviewer until the native observation and its hashes
are frozen. The controlled comparison path revalidates the sealed full-fixture
binding against live repository bytes before releasing the oracle.

## Fail-closed MSPDI calendar finding

All twelve fixtures require the exact continuous `CAL-24X7` calendar.
Microsoft Support describes the built-in **24 Hours** calendar as 12:00 AM to
12:00 AM every day. The official Project XML schemas provide `FromTime` and
`ToTime`, but the published XML reference does not define whether equal
`00:00:00` endpoints represent a 24-hour interval or a zero-length interval.
Using `23:59:00` would lose one minute per day and violate the frozen exact-hour,
zero-rounding contract.

The pilot therefore fails closed:

- every manual build sheet uses the documented built-in **24 Hours** calendar;
- the known-safe task, constraint, relationship and lag mappings are recorded;
- every MSPDI adapter realization is `preparation_blocked`;
- no apparently valid XML file is generated; and
- adapter preparation can resume only after an approved characterization or
  change-control decision establishes the exact calendar serialization.

This is a mapping-evidence gap, not a native failure result.

## Documented mappings retained for later use

The official Project 2010 SDK schema provides the versioned namespace
`http://schemas.microsoft.com/project/2010`, `SaveVersion` 14,
`NewTasksAreManual=0`, and task `Pinned=0`. Other retained mappings are task
`Type=1` for fixed duration, `EffortDriven=0`, SNET `ConstraintType=4`, and
predecessor types FF=0, FS=1, SF=2 and SS=3. `LinkLag` is signed tenths of a
minute, so the pilot values are 0, +1200 and -1200 with hour format 5.

These mappings are preparation facts only. Microsoft Project must still verify
the imported task mode, task type, effort-driven state, relationship, lag,
calendar, calculation mode and levelling status before a native run.

The normalizer may retain one exported structural Project summary task only
when it has UID 0, ID 0, `Summary=1` and no predecessor link. That record is
unclaimed structural evidence: it is not a canonical activity, cannot satisfy
activity coverage and contributes no claimed coordinate. This bounded decision
is source-bound in the generated mapping register.

The manual track separates three settings that must not be conflated:

- tasks are automatically scheduled;
- the Microsoft Project application calculation mode is **Manual** while the
  source realization is constructed and frozen; and
- the protocol state is `constructed_not_calculated` until the freeze command
  writes `frozen_before_native_calculation`.

The operator must also verify scheduling from the project start date
(`ScheduleFromStart=true`). The exported XML is checked independently after
execution, but that post-execution check cannot repair a missing pre-execution
capture.

The output normalizer is intentionally limited to the reviewed Project 2010
MSPDI namespace with `SaveVersion=14`. Before execution, the operator must
confirm that the identified desktop build can export that exact dialect. A
newer or different build that emits another namespace/version is not treated as
equivalent; its run stops as inconclusive until a separately reviewed mapping
exists.

Reviewed primary mapping sources are the
[Project 2010 SDK](https://www.microsoft.com/en-sa/download/details.aspx?id=15511),
[Project calendar XML reference](https://learn.microsoft.com/en-us/office-project/xml-data-interchange/calendar-element?view=project-client-2016),
[weekday XML reference](https://learn.microsoft.com/en-us/office-project/xml-data-interchange/weekday-element?view=project-client-2016),
[Microsoft's 24 Hours calendar definition](https://support.microsoft.com/en-US/project/create-a-new-base-calendar),
[task-mode reference](https://support.microsoft.com/en-US/project/task-mode-task-field),
[application calculation-mode API](https://learn.microsoft.com/en-us/office/vba/api/project.application.calculation),
[resource-levelling API](https://learn.microsoft.com/en-us/office/vba/api/project.application.levelingoptions),
and the official Project XML [summary-UID example](https://learn.microsoft.com/en-us/office-project/xml-data-interchange/elemtype-element?view=project-client-2016),
[Task element](https://learn.microsoft.com/en-us/office-project/xml-data-interchange/task-element?view=project-client-2016)
and [Summary element](https://learn.microsoft.com/en-us/previous-versions/office/developer/office-2007/bb968468(v=office.12)), together with the
[project-summary visibility property](https://learn.microsoft.com/en-us/office/vba/api/project.project.displayprojectsummarytask).
The generated mapping-source register records the downloaded SDK and embedded
schema hashes so a later reviewer can reproduce the exact source inspection.

## Commands

```bash
python -m deterministic_scheduling_core prepare-msproject-relationship-pilot
python -m deterministic_scheduling_core verify-msproject-relationship-pilot
python -m deterministic_scheduling_core freeze-msproject-native-input --help
python -m deterministic_scheduling_core analyse-msproject-native-output --help
python -m deterministic_scheduling_core record-msproject-native-attempt-stop --help
```

If a runbook stop condition prevents a complete analysis bundle, the dedicated
stop recorder retains a canonical, repository-bound, hash-only account of the
artifacts that actually exist. It refuses overwrite, applies the frozen
condition/outcome mapping, never fabricates missing stage hashes, never emits a
native-run record or `executed_pass`, and is not eligible for claim ingestion.
The tracked `native-attempt-stop-record-template.json` is an instruction
document, not evidence. Formal native claim ingestion remains unavailable for
a stopped attempt; any retry requires a new frozen realization.

Preparation writes only deterministic, non-native evidence. The freeze command
hashes a supplied native input before result observation and refuses to
overwrite an existing realization. It refuses the adapter track while the case
is `preparation_blocked`. The analysis command normalizes only controlled
Project 2010 XML evidence, rejects off-grid timestamps without rounding, and
cannot declare `executed_pass` or a full-profile gate.

The tracked kit is immutable. Operators copy the selected per-case template
under
`tracks/manual_native_semantic_parity/environment-capture-templates/` and the
selected case sheets into the ignored controlled-execution workspace; they do
not fill in tracked files. Only the template's `capture` object is written as
canonical `environment.json`. Every required placeholder is completed except
`status_date`, which must remain null for these no-status relationship cases.
Prefilled required settings are plans, not observations. The operator must fill
each `observed_product_settings` value plus operator/reviewer identities and
times from native evidence; the generated calendar-continuity and leveling
attestations are null until observed. The exact six-action log, six independent-evidence roles, displayed
progress-rescheduling settings, and observed Project ID/Unique ID/name map are
required. Track B receives a separate pre-execution manifest that hash-binds
the same native source file, exact environment realization and its complete,
repository-revalidated prerequisite Track A manifest before the first
calculation.

The generated `operator-runbook.md` contains copy-ready Track A and Track B
freeze commands, exact track-specific post-execution action-log templates and
both analysis commands. The construction action times must be strictly
chronological and no later than the freeze time. For analysis, each
`--stage-artifact ROLE=PATH` value is a file path that the analyser hashes, not
a caller-computed digest. `--post-execution-action-log PATH` supplies the exact
ordered track action record and each repeatable `--evidence-artifact ROLE=PATH`
binds one of the six independently verified evidence files. The attestation
must contain the recomputed action-log, stage-artifact and evidence-artifact
hash maps. Track A accepts only
`native_calculated_file_sha256`. Track B requires exactly
`native_pre_close_file_sha256`, `native_pre_close_output_sha256`,
`native_reopened_file_sha256`, `native_recalculated_file_sha256`, and
`native_post_recalculate_output_sha256`. Track B analysis also requires
`--prerequisite-manual-case-realization-manifest` so the analyser can revalidate
the complete repository-bound Track A prerequisite; that flag is forbidden on
other tracks.

`pilot-index.json` also records a domain-separated input-identity projection
and SHA-256 over the pilot ID, ordered case IDs, frozen preregistration/profile,
operator-safe source-only projection hashes, and generated mapping-source-register
raw hash. It does not expose full-fixture paths or hashes. Phase 1 governance
recomputes that identity from live bytes and requires the experiment-register
`input_hash` to match. Full fixture bytes remain independently frozen and are
bound only by the sealed comparison artifacts.

## Native work still required

After manual merge, an identified Microsoft Project desktop edition, version
and build must be used. The operator must copy the working sheets, capture the
Windows/product environment, set Project Information > Start Date to the frozen
origin, schedule from the project start date, set application calculation mode
to Manual, select the built-in 24 Hours calendar, enter explicit `4h`/`3h`
durations, record the displayed task ID and Unique ID mapping, disable and never
run resource levelling, select automatic fixed-duration non-effort-driven
tasks, freeze each applicable track before
calculation, calculate natively, save and hash each required stage, export the
reviewed Project 2010 XML dialect, complete the post-execution attestation,
retain screenshots or reports, run the analyser, and obtain independent
review. Until that happens, no native result exists.
