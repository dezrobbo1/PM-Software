# Native validation evidence boundary

The files in this directory preregister future, product-specific native
experiments. They are not native results and do not establish compatibility.

## Frozen plans and profiles

- `preregistrations/p6-semantic-microcases-v0.1.json` binds the P6 plan to
  `profiles/p6-semantic-comparison-profile-v0.1.json`.
- `preregistrations/microsoft-project-semantic-microcases-v0.1.json` binds the
  Microsoft Project plan to
  `profiles/microsoft-project-semantic-comparison-profile-v0.1.json`.
- `schemas/native-validation-preregistration.schema.json` is a closed schema for
  both document types.

The P6 and Microsoft Project profiles have independent claim subsets,
configuration rules and evidence roots. A result under one profile cannot
satisfy the other.

P6 has 47 claim-eligible semantic cases. `SEM-STA-045` is
characterisation-only because `reference-v0.3` deliberately has no forecast
oracle for P6 Actual Dates behaviour.

Microsoft Project has 45 claim-eligible semantic cases. `SEM-STA-043`,
`SEM-STA-044` and `SEM-STA-045` are characterisation-only; the profile does not
invent Microsoft Project equivalence to P6 Retained Logic, Progress Override or
Actual Dates policies.

`SEM-DET-049` and `SEM-DET-050` are excluded from both native semantic profiles.
Resource levelling remains a separate future comparator experiment.

## Three independent evidence tracks

1. `manual_native_semantic_parity` tests the bounded calculation after a
   preregistered native case realisation. Controlled, independently checked
   transcription is allowed. It cannot establish interchange.
2. `saved_file_reopen_recalculate_stability` tests the same native file before
   and after save, close, reopen and native recalculation. It cannot establish
   semantic parity or adapter interchange by itself.
3. `adapter_interchange_round_trip` uses P6 XML or MSPDI XML and prohibits
   transcription. It can establish only the profile's bounded adapter subset,
   not safe production round-trip.

Each track has its own required stage hashes and pass condition. There is no
aggregate `compatible` status.

## Evidence retention

Raw native files may remain under ignored `native-files/` roots because they may
contain proprietary or restricted data. No repository claim may rely only on an
ignored local file. Before any bounded claim, a redacted manifest must be
committed under `native-validation/evidence-index/` with the hashes, product
build/configuration, outcomes, review disposition, controlled artifact location
and retention owner required by the preregistration.

The preregistration files remain `preregistered_not_executed`. Results are new,
separate evidence records; they never rewrite a preregistration or its oracle.
Any protocol or oracle change requires a new preregistration and profile ID.

Even a complete profile pass cannot establish full P6 compatibility, full
Microsoft Project compatibility, MPP binary compatibility, safe production
round-trip, optimiser superiority, practitioner acceptance or buyer validation.

## Prepared pilot kits

`pilot-kits/microsoft-project-relationship-v0.1/` is a deterministic,
preparation-only subset for `SEM-REL-001` through `SEM-REL-012`. It keeps manual
build instructions, per-case environment-capture templates, independent review
sheets and sealed expected outputs in separate paths. Operator-visible packets
bind oracle-free source-only case projections; only the sealed comparison
artifact binds the matching full fixture path and bytes. The completed
capture must record the exact observed Project ID/Unique ID/name mapping,
Schedule From Start, native Manual calculation mode, the separate pre-calculation
protocol state, structured action log, progress settings and evidence roles.
Generated required values are plans rather than observations: every
`observed_product_settings` record requires the native value, operator and
independent-review identities, and RFC 3339 observation times. Calendar
continuity and leveling attestations remain null in the tracked templates, and
pre-execution actions must be strictly chronological and no later than freeze.
Its status is `prepared_not_executed`; it contains no native result.

Native execution uses split control. The operator-visible execution packet is
assembled from an explicit allowlist of the source-only projection, build and
review sheets, environment/action/attestation templates, and runbook material
needed for the selected case and track. `pilot-index.json` is the operator index,
and `pilot-kit-manifest.json` is the allowlisted pre-observation packet manifest.
Neither may include a sealed expected artifact, sealed path, sealed digest,
oracle-bearing fixture, or comparison-custodian metadata. The repository
checkout is not an operator packet: frozen semantic fixtures committed for
protocol verification contain their expected results, so an operator must not
use an unrestricted checkout while constructing or calculating a native case.

For Track A, the comparison custodian retains the case-specific sealed control.
The analyser first normalizes the observed native output, creates and durably
syncs the normalized file, and verifies its hash; only then does it automatically
resolve and open the repository-held comparison control. The operator does not
release or inspect it. Track B has no oracle comparison at any stage: it rejects
a supplied sealed control and compares only the independently normalized
pre-close and post-recalculation observations.

Track A and Track B have separate exact post-execution action-log templates.
The analysis command receives one with `--post-execution-action-log`, receives
each actual screenshot/report as repeatable `--evidence-artifact ROLE=PATH`,
and recomputes the action-log, stage and evidence SHA-256 values bound by the
post-execution attestation. Track C has no executable template while its MSPDI
input mapping remains blocked.

Mandatory stop conditions use the separate
`record-msproject-native-attempt-stop` command. It binds the live pilot, case,
track, source-only case projection, preregistration and profile; hashes only evidence that actually
exists; refuses overwrite; and emits a non-claimable stopped-attempt record,
never a native-run record or pass. The tracked
`native-attempt-stop-record-template.json` is instructions only. Missing stage
hashes must not be invented, and retry requires a new frozen realization.

The pilot index's domain-separated input identity binds the ordered twelve
cases, frozen preregistration/profile, source-only projection bytes and
mapping-source-register bytes. Governance recomputes it from the live tree
before accepting the experiment-register input hash. Full fixture bindings are
kept solely in the sealed comparison files.

The manual track is prepared around Microsoft Project's documented built-in
**24 Hours** calendar. MSPDI adapter creation is `preparation_blocked` because
the official XML reference does not establish the exact serialization of a
continuous midnight-to-midnight interval. The blocker records are not XML
inputs and cannot support an adapter or compatibility claim.
