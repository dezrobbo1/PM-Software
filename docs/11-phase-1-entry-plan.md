# Phase 1 Entry Plan

## Phase 1 objective

Implement and test the declared reference semantic subset. Do not implement the optimiser first.

## Mandatory entry checks

Before Phase 1 code is added:

```bash
python -m unittest discover -s tests -v
python tools/validate_phase0.py
```

Both commands must pass from a clean Git checkout. The manifest must exactly cover the tracked protocol files, and the consolidated protocol must match the numbered authoritative documents.

## Work packages

### WP1 — Repository and runtime pin

- choose implementation language/runtime;
- pin runtime and dependency versions;
- record platform fingerprint;
- adopt canonical JSON and SHA-256 implementation;
- keep CI running schema, negative-guard and manifest validation.

### WP2 — Canonical loader

- parse canonical schedule fixtures;
- reject duplicate IDs, unresolved references and WBS cycles;
- reject invalid, overlapping or out-of-horizon calendar intervals;
- expand explicit working intervals;
- preserve source-specific fields without interpreting them;
- represent baseline, approved forecast and proposed scenario separately;
- enforce complete coverage for every supplied approved forecast and proposed scenario, preservation of frozen coordinates and case-specific objective-vector shape;
- validate saved state spans against selected duration and calendar intersections.

### WP3 — Reference CPM kernel

- activity-calendar duration arithmetic;
- FS, SS, FF, SF;
- signed lag on the successor activity calendar;
- reject non-null explicit lag calendars from the active profile until a direct fixture exists;
- milestones;
- included constraints;
- reject preserved-only `fixed_start` and `fixed_finish` from the active `reference-v0.3` execution path until direct fixtures exist;
- restricted actual/status policies;
- restricted float calculation.

### WP4 — Independent validator

- relationship satisfaction;
- duration/calendar satisfaction;
- capacity-one exclusive resources; reject cumulative capacity from the active profile until a direct fixture exists;
- immutable actuals;
- require deterministic in-progress status time;
- expected assertion comparison;
- deterministic serialisation and hash;
- execution-record and explanation-schema validation;
- coordinate-derived movement checks, canonical cause resolution, RFC 6901 counterfactual patches and calculation-trace evidence;
- explicit native round-trip disposition and zero-gap proof for optimal results.

### WP5 — Run 50 semantic fixtures

- save one execution record per case;
- retain all failures;
- require complete evidence and hashes before using an `executed_*` label;
- do not modify expected outputs without change control.

### WP6 — First native comparison

Microsoft Project is the practical first comparator only if lawful local access exists. Record exact version/settings, create native equivalents of selected microcases, reopen/recalculate and populate the compatibility matrix.

## Phase 1 exit criteria

- all 50 reference fixtures structurally and semantically executed;
- zero unexplained reference-profile discrepancies;
- deterministic hash equality across repeated runs;
- native test evidence clearly separated from untested profiles;
- no optimiser or product claim made from reference tests alone.
