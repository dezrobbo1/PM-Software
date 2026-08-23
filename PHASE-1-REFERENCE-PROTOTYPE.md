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
  supplied-state coverage and exact frozen-suite discovery;
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

`deterministic-v0.2` pins the canonical serializer and reference-kernel build
before first execution. Each declared case saves:

- canonical input;
- calculated output and complete selected state;
- independent validation evidence;
- a schema-valid structured calculation trace;
- a runtime/execution identity with exact Python version and a non-identifying
  platform fingerprint;
- an evidence bundle and schema-valid execution record.

All deterministic paths are relative POSIX paths. Hashed artifacts contain no
hostnames, usernames or absolute local paths. The execution record retains an
honest RFC 3339 wall-clock `executed_at` value, but `deterministic-v0.2` defines
the execution-record identity hash over the canonical record with only that
field omitted. Every calculation-bearing and classification field remains in the
hash. Output, selected-state, validation, explanation, identity and bundle hashes
include their complete canonical documents.

`SEM-STA-045` saves a native-validation disposition and a non-executed execution
record. In accordance with execution-record schema `0.1.4`, that record contains
no fabricated input, output, selected-scenario, explanation or evidence-bundle
hash.

## Commands and acceptance result

```bash
python -m pip install --disable-pip-version-check -e .
python -m unittest discover -s tests -v
python tools/validate_phase0.py
python -m deterministic_scheduling_core run-semantic-suite
python -m compileall -q src tools tests
git diff --check
```

The suite acceptance condition is exactly 49 `executed_pass`, one
`native_validation_required`, zero unexplained failures and stable hashes and
case ordering across at least three fresh processes.
