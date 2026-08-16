# Phase 1 Entry Plan

## Phase 1 objective

Implement and test the declared reference semantic subset. Do not implement the optimiser first.

## Work packages

### WP1 — Repository and runtime pin

- choose implementation language/runtime;
- pin runtime and dependency versions;
- record platform fingerprint;
- adopt canonical JSON and SHA-256 implementation;
- set CI to run fixture/schema validation.

### WP2 — Canonical loader

- parse canonical schedule fixtures;
- reject duplicate IDs and unresolved references;
- expand explicit working intervals;
- preserve source-specific fields without interpreting them.

### WP3 — Reference CPM kernel

- activity-calendar duration arithmetic;
- FS, SS, FF, SF;
- signed lag;
- milestones;
- included constraints;
- restricted actual/status policies;
- restricted float calculation.

### WP4 — Independent validator

- relationship satisfaction;
- duration/calendar satisfaction;
- resource capacity where declared;
- immutable actuals;
- expected assertion comparison;
- deterministic serialisation and hash.

### WP5 — Run 50 semantic fixtures

- save one execution record per case;
- retain all failures;
- do not modify expected outputs without change control.

### WP6 — First native comparison

Microsoft Project is the practical first comparator only if lawful local access exists. Record exact version/settings, create native equivalents of selected microcases, reopen/recalculate and populate the compatibility matrix.

## Phase 1 exit criteria

- all 50 reference fixtures structurally and semantically executed;
- zero unexplained reference-profile discrepancies;
- deterministic hash equality across repeated runs;
- native test evidence clearly separated from untested profiles;
- no optimiser or product claim made from reference tests alone.
