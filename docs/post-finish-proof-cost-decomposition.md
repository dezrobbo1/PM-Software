# Post-finish proof and pipeline cost decomposition (diagnostic v0)

PR #48 replaced the dominant finish minimisation with exact LB1-seeded proof. This experiment measures the unchanged authoritative pipeline, then separately asks whether each later objective can be attained at its known optimum and whether one integer unit better is infeasible. Known values are diagnostic only: production still calculates finish, timing and canonical blocks normally.

## Verified merged baseline

`157a4d481ee4fd0abf9eb57cb2ffcff0a8913af2` was the current merged main. Its push workflows for work-method, accepted history, rolling status, canonical proof, converged scale, professional semantics, professional classifier and POC smoke completed successfully; the POC browser-smoke job was successful. The PR #48 adoption workflow passed on its feature head. Before any edits, public plans produced hashes `d54db4bc5f6cdd64b1ca3d8fd3f92b9f45103cae2230685e81363936db746761` (small named), `733a4023ff6c78735aa4ccc5d8003a1f31ecde80f3851ffadbd4dadfa2100acb` (professional), and `0698e2c95e7aed5ee35d7d343349e77b88e39121bfbad41fa865c6818d923410` (64/48). The focused experiment checks these exact hashes on each run.

## Stage method

The diagnostic calls the public scheduler first and retains its non-persisted timings. A fresh compile then uses exactly the production compiler and block builder. For global timing, it fixes the exact finish and clones the same objective-free stage context three times: minimise timing; ask satisfaction at the production optimum; ask infeasibility one unit below. For canonical block *i*, it fixes finish, global timing and precisely the preceding block values, assembles the production digit witnesses, and repeats those three questions on clones of the same context. Each before-delta proto text SHA-256, variable count, constraint count and absent-objective flag are retained. The fresh optimisations use a newly created solver with production parameters; the actual public stage metrics are the sequential/reused-solver control. Fresh and sequential objective values agree. Neither the experiment nor a diagnostic solution is used to produce an authoritative plan.

The inventory retains every block's order, extrema, integer safety bound, encoded value, coefficients and method/mode/placement digit counts. It reconciles every declared canonical digit exactly once. Zero digits are not treated as proof of inactivity. SAT and UNSAT statistics are solver response counters, not certificates extracted from callbacks; each final solver status is asserted. The proto digest compares stage contexts **within one OR-Tools environment**, not across OR-Tools versions.

## Primary observations on the retained 64/48 case

The unchanged plan has finish `F=19`, global timing `G=14674`, 5,626 placement alternatives and nine canonical blocks. The fresh complete diagnostic run records its exact model and all per-stage counters in the JSON artifact. A representative local measurement (no CI performance threshold) gave:

| Actual production proof | Deterministic seconds | Interpretation |
| --- | ---: | --- |
| Finish queries | 0.068463 | Exact LB1 hit |
| Global timing | 0.089326 | 42% of post-finish proof |
| Canonical block 000 | 0.081590 | 67% of canonical proofs; eight method and 54 mode digits |
| Other eight blocks combined | 0.039578 | Remainder of canonical proofs |
| Post-finish total | 0.210494 | Global plus all blocks |

The block inventory's later blocks contain the remaining ten modes and all placement digits. Global timing minimisation costs about 0.089 deterministic seconds, SAT at `G` about 0.081 and UNSAT at `G−1` about 0.081. For block 000 the corresponding values are about 0.082, 0.032 and 0.018. Those separate solves do **not** add to production cost and do not prove that any particular digit caused the difference. In this environment the fresh optimisation's deterministic counters equal the actual sequential-stage counters; this does not establish universal solver-state behaviour across versions.

The wall accounting uses input copy, validation, productive compilation, placement generation, CP-model assembly, LB1 derivation, finish queries, global proof, block assembly, block proofs, extraction, independent allocation and stored-plan validation exactly once. `build_ms`, `solve_ms`, and `independent_validation_ms` are overlapping summaries and are *not* added again. A residual is explicitly reported and is not assigned to a subsystem. A representative run observed about 97 ms in preparation/assembly, 1,075 ms of solver calls, 22 ms after solve, and 29 ms residual; individual wall observations vary with environment.

The small named-resource fixture (including multiple finish queries), professional suspension/workface/deadline/inactive-method fixture, and anonymous whole-activity group control retain exact public plan semantics and physically valid plans. The 8/16/32/48/64 one-placement ladder and 129/513/1537/3841-placement eight-activity density ladder report every production stage and non-overlapping pipeline phase; no universal curve or speedup is inferred. The 160/120 professional challenge remains classification-only: first barrier 64 declared activities, 64,068 raw and 64,032 deadline-eligible placements; no limit is increased and no forbidden solve is attempted.

## Interpretation and boundary

Solver classification **S-B** on the material 64/48 case: canonical proofs together exceed global timing and block 000 exceeds all other blocks together. The controls differ in relative *tiny* stage costs; they do not establish a general block-specific speedup target. Pipeline classification **P-A** on this environment: the solver's observed wall time remains the largest non-overlapping family, even though deterministic proof time has fallen substantially. This avoids equating ~0.21 deterministic seconds with wall milliseconds. It is reasonable to investigate the exact first-block proof boundary next, but no solver redesign is justified solely by being the largest solver stage; repeated wall evidence and the actual amount of addressable cost should precede adoption. This milestone implements **no optimisation**.

The module lives outside `scheduling/`. It changes no compiler, proof policy, accepted history, lineage, plan schema/hash, resource/workface/deadline semantics, stage budget, safety limit, or scale admission. Neither production nor POC smoke imports the experiment. The dedicated PR workflow retains exact-head JSON, tests and checksums and tolerates partial failure evidence.
