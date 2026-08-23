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
