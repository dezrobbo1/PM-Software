# Phase 1 Reference CPM Prototype

## Purpose and claim boundary

This is an executable research instrument for the frozen `reference-v0.3`
semantic profile. It is not a production scheduling engine, optimiser, project
management application or native-file adapter. It makes no Primavera P6 or
Microsoft Project compatibility claim and no superiority claim.

The Phase 0 fixture corpus, expected coordinates, objective policy, semantic
profile, decision gates and stop conditions are unchanged.

## Package architecture

- `canonical`: schema loading, stable ordering, reference resolution, complete
  supplied-state coverage, exact frozen-suite discovery and pinned raw fixture
  and catalogue byte identities;
- `calendars`: half-open interval intersection, productive duration and signed
  successor-calendar lag;
- `cpm`: the bounded reference producer and objective-v0.3 ranking used only for
  the two preregistered two-order resource cases;
- `validation`: an independent unit-coordinate validation path plus evidence,
  schema and hash-consistency checks;
- `execution`: the 50-case harness and deterministic artifact writer;
- `provenance`: `dsc-canonical-json-v1`, SHA-256 and execution-platform identity.

The independent result validator does not import or call the CPM kernel. The
producer consumes only the canonical schedule plus frozen case identity/category;
it never receives the fixture's expected result object. Expected values enter
only the validator as an external preregistered oracle.

## Executable semantics

The kernel implements task and start/finish milestone spans; explicit productive
working intervals; FS, SS, FF and SF relationships; positive and negative lag on
the successor activity calendar; project-start, start-no-earlier-than and
finish-no-earlier-than lower bounds; completed actual immutability; in-progress
remaining work at deterministic status time; retained-logic and progress-override
treatment; capacity-one exclusive resource availability; the two reviewed
capacity-one order cases; the restricted float fixtures; and deterministic
project finish.

The loader preserves but execution rejects alternate lag calendars, cumulative
capacity, fixed-start/fixed-finish, execution modes, frozen-horizon execution and
operational constraints. `actual_dates` remains native-validation-only. Any
contended resource network other than `SEM-DET-049`/`050` fails closed.

## Deterministic evidence

Historical `deterministic-v0.2` pinned the canonical serializer and
reference-kernel build before first execution. Active `deterministic-v0.3`
preserves those pins and adds a SHA-256-locked dependency closure,
exact source-inventory verification, named portable success/failure and environment evidence projections
and explicit output-directory ownership. Each declared case saves:

- canonical input;
- calculated output and complete selected state;
- independent validation evidence;
- a schema-valid structured calculation trace;
- a runtime/execution identity with exact Python version and a non-identifying
  platform fingerprint;
- a portable semantic-result sidecar (or portable failure-result sidecar) and an environment-evidence sidecar;
- a native-requirements sidecar with separate P6 and Microsoft Project entries;
- an evidence bundle and schema-valid execution record.

Calculation traces identify and bind the actual governing calendar, relationship,
date constraint, preserved actual event or capacity-one resource order for their
focus activity. Complete selected-state hashes include the distinct
`remaining_start` coordinate for in-progress work. Duplicate selected activity
IDs are rejected before coverage checks. Reusing a managed suite output directory
first requires the exact harness ownership marker; absent, altered or symbolic
markers fail before any generated entry is removed. Unrelated entries are
rejected and preserved.

All deterministic paths are relative POSIX paths. Hashed artifacts contain no
hostnames, usernames or absolute local paths. The execution record retains an
honest RFC 3339 wall-clock `executed_at` value, but `deterministic-v0.3` defines
the execution-record identity hash over the canonical record with only that
field omitted. Every calculation-bearing and classification field remains in
that environment-bound hash. The portable semantic-result projection binds the
fixture/input, source manifest, dependency lock, semantic/objective/kernel/profile
versions, output, selected state, independent validation and calculation trace,
while excluding the exact execution identity. The environment projection binds
that portable hash to the verified locked distribution closure, Python/runtime
platform, full explanation, evidence bundle and execution record. No
cross-version determinism is promised.

`SEM-STA-045` saves a native-validation disposition and a non-executed execution
record. In accordance with execution-record schema `0.1.4`, that record contains
no fabricated input, output, selected-scenario, explanation or evidence-bundle
hash. The frozen record schema retains one native-system field, so the Phase 1
native-requirements sidecar and the two product-specific preregistrations carry
the separate pending P6 and Microsoft Project requirements without widening the
schema or claiming a native result.

## Commands and acceptance result

```bash
python -m pip install --require-hashes --only-binary=:all: -r requirements/phase1-ci.lock
python -m pip install --no-deps --no-build-isolation -e .
python -m unittest discover -s tests -v
python tools/validate_phase0.py
python tools/validate_phase1_governance.py
python -m deterministic_scheduling_core run-semantic-suite
python -m compileall -q src tools tests
git diff --check
```

The suite acceptance condition is exactly 49 `executed_pass`, one
`native_validation_required`, zero unexplained failures and stable named hash
domains and case ordering across at least three fresh processes in the same
declared environment. Equality of portable hashes may be compared across
environments; equality is evidence from those runs, not a cross-version promise.
