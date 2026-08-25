# Phase 1 evidence and repository-governance hardening

Date: 24 August 2026

Trigger: post-merge review of the bounded Phase 1 reference prototype

Classes: deterministic, validation, evidence governance and repository governance

## Existing evidence and change boundary

Reference execution results existed before this amendment under
`deterministic-v0.2`. The retained historical suite hash is:

`66e667afc94f4f32dad3cd098e933113645e6047669951e6cc39fde4ec4bef6c`

No P6 run, Microsoft Project run, optimiser benchmark, native round trip,
practitioner trial or buyer trial had been executed. This amendment does not
reinterpret, replace or erase the v0.2 result.

The 50 frozen fixtures and their expected values, `reference-v0.3`,
`objective-v0.3`, execution-record schema `0.1.4`, calculation kernel and all
decision gates remain unchanged. No optimiser, native adapter or native
application execution is included.

## Deterministic-v0.3

`deterministic-v0.3` supersedes v0.2 only for future execution evidence. It:

- pins every direct, transitive and build distribution in
  `requirements/phase1-ci.lock` and requires SHA-256 wheel verification;
- verifies the raw dependency-lock hash, exact locked distribution versions and
  the complete canonical source inventory before executing the suite; the lock
  is supported on CPython 3.11/3.12 for Linux x86_64;
- preserves honest execution timestamps while keeping the existing
  execution-record projection that omits only `executed_at`;
- publishes a portable semantic-result projection that binds source, input,
  semantic/objective/kernel/profile versions, output, selected state,
  independent validation and structured calculation trace, plus a portable
  failure-result projection that binds the retained failure outcome, without
  embedding the exact runtime identity; and
- publishes a separate environment-evidence projection that binds the portable
  result to the exact Python/runtime platform, locked dependency closure, full
  explanation, evidence bundle and execution record.

The portable/environment terminology is an evidence-governance distinction
introduced by this amendment. It does not create a cross-version determinism
promise. Equality across environments is established only by actually obtaining
equal portable hashes from those runs.

## Evidence safety corrections

The harness now creates a fixed ownership marker in a new or empty output
directory. It will replace prior generated entries only when that exact regular
marker is present. Missing, altered or symbolic markers and unrelated entries
fail before deletion. The marker itself is preserved across runs.

The evidence validator now rejects duplicate selected activity IDs before
coverage checks and reconstructs the complete expected execution identity. An
input-only identity check is insufficient because an altered platform or
dependency environment could otherwise be rehashed into an internally
consistent but ungoverned bundle.

## Native evidence remains separate and open

The following independent preregistrations remain at status
`preregistered_not_executed`:

- `p6-semantic-microcases-v0.1`; and
- `microsoft-project-semantic-microcases-v0.1`.

Both bind the same 48-case execution corpus but use separate, closed-schema
comparison profiles, exact normalized fields, zero tolerances, approved
transformations, product configuration and distinct ignored evidence roots. The
P6 claim subset contains 47 cases; `SEM-STA-045` is characterization-only because
the reference profile deliberately has no P6 Actual Dates forecast oracle. The
Microsoft Project claim subset contains 45 cases; `SEM-STA-043`, `044` and `045`
are characterization-only rather than invented equivalents of P6 Retained Logic,
Progress Override or Actual Dates. `SEM-DET-049` and `050` remain excluded from
both native semantic profiles and do not establish resource-levelling parity.

Each plan separates manual native semantic comparison, saved-file
reopen/recalculate stability and controlled adapter/interchange round trip. A
manual creation or transcription cannot satisfy the P6 XML or MSPDI interchange
gate, and no track creates a general product-compatibility status. Raw native
artifacts may remain outside Git, but any future bounded claim requires a
committed redacted evidence manifest containing hashes, build/configuration,
outcomes, independent review, a controlled location and retention owner.

The P6 and Microsoft Project records cannot satisfy one another. Every reference
suite case also writes a hashed `native-requirements.json` sidecar with separate
product entries. Portable reference execution is not native compatibility
evidence, and neither preregistration is a native result.

## Repository governance

Both validation workflows run for pushes to `main` and pull requests targeting
`main`, install the same hash-locked environment and expose stable, unique check
names: `phase0-validation` and `phase1-validation`.

`.github/repository-governance.json` records an optional future branch-protection
profile. Live GitHub ruleset enforcement is not required for this owner-operated
research repository and is not a completion or merge gate. The normal working
practice remains feature branches, pull requests, green CI and review. Any future
claim that live protection is active must still be independently verified
through GitHub.

## Research basis and claim discipline

The supplied technical-feasibility research treats determinism as a complete
execution-contract property, requires recomputable structured explanations, and
keeps native reopen/recalculate/re-import evidence separate from reference
execution. The supplied practitioner research retains P6 or Microsoft Project as
authority while native-feature, interchange, trust, competitive and buyer gates
remain open. This amendment implements those evidence boundaries without turning
an unexecuted gate into a result.
