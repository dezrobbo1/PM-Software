# Deterministic Scheduling Core — Phase 0 Protocol Freeze

Status: **Phase 0 complete at `phase0-0.1.2`; implementation not started**  
Research date: **16 August 2026**  
Scope: **Separate from Shutdown Tracker**

This repository-ready bundle freezes the experiment before any scheduling or optimisation code is written. Its purpose is to prevent the prototype from being adjusted after results are seen.

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
- Schemas and blank experiment registers
- Structural and negative-regression validation, continuous integration, and complete SHA-256 manifest

## Validate the bundle

Run the negative regression suite and the full protocol validator from a clean Git checkout:

```bash
python -m unittest discover -s tests -v
python tools/validate_phase0.py
```

The checks validate all JSON Schemas and 50 fixtures, enforce date-time formats, stable-ID and reference integrity across current and scenario states, reject invalid calendars, frozen coordinates and incomplete expected results, verify the exact frozen objective policy and required register set, ensure the consolidated protocol mirrors its authoritative documents, and require the SHA-256 manifest to cover exactly the intended tracked files.

## Immediate next implementation milestone

Phase 1 may begin only after this protocol is reviewed and accepted. Phase 1 is limited to:

1. a canonical-model loader;
2. a reference CPM kernel for the declared `reference-v0.1` subset;
3. an independent validator;
4. execution of the 50 semantic fixtures;
5. Microsoft Project native comparison where access is available.

The optimiser is not the first implementation milestone.
