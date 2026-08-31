# PM-Software — scheduling proof of concept

**Status: active proof of concept**

This repository now has one purpose: determine whether a small constraint-based scheduler can produce a useful, inspectable schedule for resource-constrained project work, particularly shutdown and turnaround-style cases.

It is not currently a production application, a Primavera P6 or Microsoft Project replacement, or a native compatibility programme.

## Current target

The next working result is a small command-line experiment that:

- loads a transparent case containing roughly 10–30 activities;
- respects activity durations and precedence;
- prevents shared resources from being used by overlapping activities;
- produces a feasible schedule;
- shows activity starts, finishes and resource-related waiting;
- compares the result with a simple baseline schedule.

The first version is successful when it runs and the result makes sense on inspection. Unsupported cases may remain unsupported.

## What already exists

The repository contains useful foundations from the earlier research phase:

- a canonical schedule loader and semantic fixtures;
- productive calendar arithmetic;
- a bounded reference CPM kernel;
- an independent result validator;
- command-line and test infrastructure;
- extensive historical protocol and Microsoft Project experiment material.

The reference kernel is deliberately narrow. It is not a general resource optimiser and currently handles only the small preregistered resource-order cases.

## Active direction

1. Add a small OR-Tools CP-SAT scheduling experiment.
2. Run one understandable resource-constrained example end to end.
3. Inspect the output and decide whether it is useful.
4. Add one practical operational restriction, such as a crane, specialist crew, workface or permit window, only after the first experiment works.
5. Increase case size only after the small result is worth pursuing.

Microsoft Project, P6, native round-trip work, full semantic parity, large-scale benchmarking and production architecture are paused. They can be revisited after the scheduling proof of concept demonstrates value.

## Development approach

Prefer the simplest implementation that demonstrates the idea. Focused happy-path tests are enough at this stage. A known limitation is acceptable. Refactor only when the existing code obstructs the next useful experiment.

The prior Phase 0 documents, schemas, registers and native-validation files remain available as research history and reference material. They are not active acceptance criteria.

## Setup

Python 3.11 or later is required.

```bash
python -m pip install -e .
python -m unittest \
  tests.phase1.unit.test_canonical_json_and_calendars \
  tests.phase1.unit.test_kernel \
  tests.phase1.unit.test_independent_validator -v
```

The proof-of-concept scheduling command will be added in the next implementation change.

## Repository map

- `src/deterministic_scheduling_core/` — reusable scheduling, calendar and validation code.
- `benchmarks/semantic/` — small historical semantic cases.
- `tests/phase1/unit/` — focused reference-kernel tests.
- `docs/` — research documentation; see `docs/README.md` for active versus historical material.
- `native-validation/` — paused Microsoft Project/P6 experiment preparation.
- `registers/` — historical evidence templates, not an active development requirement.
- `docs/archive/` — previous top-level protocol snapshots, CI workflows, governance profile and manifest.
