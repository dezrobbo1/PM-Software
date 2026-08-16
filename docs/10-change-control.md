# Phase 0 Change Control

## Freeze rule

The protocol is frozen at `phase0-0.1.0` before scheduling results exist.

Any change to semantics, objective levels, tie-breaking, comparator settings, metrics, case inputs, expected outputs, pass criteria or exclusions must:

1. receive a new version;
2. state the reason;
3. identify whether results already existed when the change was proposed;
4. list affected cases and prior outputs;
5. preserve the superseded version;
6. regenerate the manifest;
7. never overwrite unfavourable evidence.

## Change classes

- `editorial`: no semantic or benchmark effect;
- `clarification`: resolves ambiguity without changing expected result;
- `semantic`: changes calculation meaning;
- `benchmark`: changes case, comparator or metric;
- `deterministic`: changes execution identity or canonicalisation;
- `scope`: changes included or excluded capability.

## Pre-registration rule

Before each new benchmark family begins, commit:

- hypothesis;
- corpus;
- comparator configuration;
- metrics;
- stop limit;
- pass interpretation;
- evidence location.

Post-result changes must be explicitly labelled exploratory and cannot replace the preregistered result.
