# Phase 1 deterministic execution pin `deterministic-v0.2`

Date: 23 August 2026

Trigger: planned Phase 1 entry requirement in `docs/04-deterministic-contract.md`

Results existing when proposed: **none**

Classes: deterministic implementation pin and runtime evidence.

The frozen `deterministic-v0.1` object is retained unchanged as the Phase 0
preregistration record. Before the first calculated execution, this amendment
adds `deterministic-v0.2` and pins:

- canonical JSON to the package-owned `dsc-canonical-json-v1` implementation;
- the executable producer to `standard-library-reference-cpm`, build
  `reference-cpm-kernel-v0.1.0`;
- CPython 3.11 or later, with the exact runtime included in each execution
  identity;
- one worker, seed zero, no wall-clock termination and the existing
  objective-v0.3 level-seven tie break;
- repository-relative POSIX evidence paths; and
- execution-record identity hashing over the complete canonical record except
  honest wall-clock `executed_at` metadata.

The serializer accepts the executable JSON domain only: UTF-8 strings normalised
to NFC, lexicographically sorted object keys, compact separators, integer time
and capacity, booleans and null. The canonical loader establishes stable-ID order
for arrays whose order is not semantically meaningful. Floating-point values are
rejected.

This amendment does not change `reference-v0.3`, `objective-v0.3`, canonical
schema `0.1.3`, execution schema `0.1.4`, any frozen fixture, any expected result,
decision gate or stop condition. It fulfils the already-preregistered requirement
to replace Phase 0 implementation placeholders with a new versioned profile
before execution.
