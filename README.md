# Deterministic Scheduling Core — Phase 1 Reference Prototype

Status: **Phase 0 frozen at `phase0-0.1.4`; bounded Phase 1 reference prototype implemented**
Research date: **16 August 2026**
Scope: **Separate from Shutdown Tracker**

The Phase 0 protocol remains frozen. Phase 1 adds a small standard-library CPM
research kernel, a canonical loader, an independent result validator and a
deterministic execution harness for the preregistered semantic corpus. Frozen
fixture inputs and expected results remain unchanged.

The bounded thesis is:

> A deterministic, auditable companion optimisation kernel may outperform priority-rule resource levelling and manual search on selected resource-constrained and operationally constrained problems while Primavera P6 or Microsoft Project remain authoritative.

This bundle does **not** claim:

- P6 compatibility;
- Microsoft Project compatibility;
- superiority over expert-configured levelling;
- superiority over experienced planners;
- safe native round-trip;
- commercial product validation;
- production readiness.

## Frozen Phase 0 outputs

- Prototype scope and explicit exclusions
- Reference semantic contract
- Canonical schedule model
- Deterministic execution contract
- Lexicographic objective policy
- Benchmark and comparator protocols
- Data-access and anonymisation plan
- Decision gates and stop conditions
- Change-control rules
- Fifty semantic micro-test fixtures
- Schemas and evidence registers, including preparation-only experiment records
- Structural and negative-regression validation, continuous integration, and complete SHA-256 manifest

## Validate the protocol and prototype

Run the negative regression suite and the full protocol validator from a clean Git checkout:

```bash
python -m pip install --require-hashes --only-binary=:all: -r requirements/phase1-ci.lock
python -m pip install --no-deps --no-build-isolation -e .
python -m unittest discover -s tests -v
python tools/validate_phase0.py
python tools/validate_phase1_governance.py
python -m deterministic_scheduling_core run-semantic-suite
```

The checks validate all JSON Schemas and 50 fixtures, enforce date-time formats, stable-ID and reference integrity across current and scenario states, preserve frozen coordinates, require deterministic status time for in-progress work, reject invalid calendars, WBS cycles, actual-state contradictions, malformed scenario spans and incomplete expected results; resolve structured explanation causes and counterfactual milestones against the canonical input; enforce RFC 6901 patch paths; verify the exact frozen semantic, objective and deterministic profiles; enforce the exact header sequence for every evidence register and typed preparation records in the experiment register; enforce the exact preregistered fixture identities and catalogue order; independently recompute every declared relationship formula and all 49 declared canonical coordinate sets; check productive duration, supported date bounds, exclusive-resource feasibility, restricted float and curated driving relationships; recompute complete objective-vector values from complete feasible selected states; require complete approved-forecast and proposed-scenario activity coverage; ensure the authoritative chapter set and consolidated protocol are exact; and require the SHA-256 manifest to cover exactly the intended tracked files.

The Phase 1 command discovers the exact 50 frozen identities, calculates all 49
declared reference results, retains `SEM-STA-045` as
`native_validation_required`, independently validates every calculated result,
and writes deterministic evidence beneath `results/phase1-semantic-suite/`.
The `results/` directory is intentionally untracked. `deterministic-v0.3`
publishes portable success/failure result hashes separately from the environment-bound
evidence hash, verifies the locked dependency closure and exact source inventory, and
will only replace an output tree carrying the exact harness ownership marker.
Every case also carries a hashed native-requirements sidecar that records P6 and
Microsoft Project separately; neither product has been executed by this suite.

## Implemented Phase 1 boundary

The executable package under `src/deterministic_scheduling_core/` is limited to:

1. canonical-model and semantic-fixture loading with schema and reference validation;
2. the declared `reference-v0.3` CPM subset;
3. an independent unit-coordinate validation path;
4. exact execution of the 50 frozen semantic fixtures;
5. canonical JSON, SHA-256 provenance and schema-valid evidence records.

No optimiser, production scheduler, native P6/MS Project input generator or
compatibility claim is included. The Microsoft Project pilot adds only
preparation, freeze, and strict output-evidence normalization tooling. Alternate
lag calendars, cumulative capacity, fixed dates,
execution modes, operational constraints and product-specific Actual Dates
forecasting fail closed at the execution boundary. See
`PHASE-1-REFERENCE-PROTOTYPE.md` for the architecture and evidence contract.

## Microsoft Project relationship-pilot preparation

`microsoft-project-relationship-v0.1` prepares twelve independent relationship
cases, manual build/review sheets, sealed comparison oracles and pre-execution
evidence tooling. Microsoft Project has not been executed and the three native
evidence tracks remain separate. Exact `CAL-24X7` MSPDI serialization is not
normatively established by the official XML reference, so adapter generation
is explicitly `preparation_blocked`; no XML is invented and no compatibility
claim exists. See `docs/phase1-msproject-relationship-pilot.md`.

```bash
python -m deterministic_scheduling_core prepare-msproject-relationship-pilot
python -m deterministic_scheduling_core verify-msproject-relationship-pilot
```
