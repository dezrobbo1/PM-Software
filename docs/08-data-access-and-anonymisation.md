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
