# Authoritative exact canonical batching v0

PR #42 compared the then-authoritative one-solve-per-digit Work-Method/productive-
time scheduler with an exact mixed-radix challenger. It found canonical proof
dominance on the retained 64/48 case. This milestone adopts that bounded proof
mechanism in `schedule_work_method_time(...)`, without changing the scheduling
policy, `PLAN_SCHEMA`, `POLICY`, input model, objective representation, or limits.

## Policy and proof boundary

The policy remains controlling finish, global weighted start timing, declared
Work-Package methods in package order, activity modes in activity order, and
activity placements in activity order. Finish and timing are still separately
proven `OPTIMAL` and fixed. Adjacent lower-order digits are grouped into exact
lexicographic blocks, each separately proven `OPTIMAL` and fixed. No `FEASIBLE`
or `UNKNOWN` result becomes an authoritative plan. Production calls the batched
path only. The private `_schedule_work_method_time_sequential_oracle(...)` retains
the original compiler label and per-digit stages for falsification tests; it is
never run during ordinary production scheduling. The PR #42 experiment now uses
the production batching primitive and compares the public authority against the
private oracle; its earlier numbers remain historical observations.

`scheduling/canonical_batching.py` is the single implementation of the block
builder. For digit maxima `M[i]`, the radix is `M[i]+1`; each coefficient is the
product of radices of less-significant digits in the same block. Therefore one
unit in a more-significant digit outweighs the full lower-order domain. Greedy
splitting occurs before the complete block maximum would exceed `2^60−1`; an
unsafe individual digit raises explicitly. Tests exhaustively compare encoded
order with vector lexicographic order, check splitting, zero-max digits and
deterministic construction. No floating-point objective weights are used.

Persisted solver metadata truthfully contains two global proofs and one proof
per block, **not** fabricated per-digit proofs. Each block records ordered digit
names, maxima, coefficients, maximum possible value, safety bound and solved
value. Non-persisted metrics separately expose each resulting canonical digit,
compiler/build phases, base size, per-stage proof counters, block assembly,
independent validation and end-to-end wall observation. Wall measurements are
not deterministic guarantees.

## Historical identity and compatibility

`tests/fixtures/canonical-batching-legacy/` was captured on verified main
`ccd1b891dfcf68fce369c67f7d6cf2e861498041` before implementation edits.
It freezes the small plan, professional workface/latest-finish plan, an accepted
history reference and status, and a one-promotion rolling cycle. The two direct
plan hashes are `3d8409958ca0b0248d78aad631ce4e0ded7f6c6a5af15ee5c6a108121fcdc7d0`
and `dea09dd2458b901faa1410c343827cc7bfd0f140ad059b1b87a47381575518bd`.
Both still pass independent stored-plan validation **with CP-SAT solve patched
to fail**. No migration or modification of their bytes is required.

`plan_hash` covers the entire persisted plan except the hash itself. New plans
with truthful block proofs therefore have different hashes even when the full
scheduling-semantic projection (everything except solver metadata and derived
hash) equals a sequential plan. This is intentional artifact identity, not a
policy change. The accepted-history frozen reference hash and status hash stay
unchanged; a recovery from that reference uses batched future proof metadata,
keeps begun methods hard, permits untouched structural recovery and matches the
sequential future-control projection. A sequential-shaped accepted plan produced
through the retained oracle also validates without a solve; unlike the frozen
reference, that accepted plan is a reconstructed control, not a frozen base-tree
artifact. A frozen rolling cycle reopens without a solve, retains its prior lineage
record, promotes a batched recovery with new truthful hashes linked to the old
reference and recovery hashes, and advances with lineage intact. No accepted
history or historical reference is rewritten.

## Retained boundary and interpretation

On one local Linux/Python 3.12.14/OR-Tools 9.15.6755 run of the exact cost
matrix, the 64-declared / 48-active case had 5,626 placements, 5,832 base
variables and 3,860 base constraints. The oracle used 138 calls, 17,887.72 ms
solve and 18,104.31 ms end-to-end. Authoritative batching used 9 canonical
blocks plus 2 global proofs (11 calls), 4,807.97 ms solve and 4,972.10 ms
end-to-end: 3.72× observed solve and 3.64× end-to-end improvement. Batched
build was 126.09 ms; placement generation 23.79 ms and CP-model assembly
93.80 ms were measured on the oracle run (independent noisy wall samples).
Of batched solve time, finish was 3,523.99 ms, global timing 279.39 ms and
all blocks 1,004.59 ms. These are observations, not a speed SLA. The dedicated
workflow retains exact-head machine-readable per-stage costs and definitions.

Exact-equivalence tests compare method/mode selection,
every placement and productive period, named and pooled demands, objective,
physical witness and every canonical digit, including inactive alternatives.
Same-environment repetition returns exactly the same plan. The 160/120 faithful
projection still accepts `exclusion_groups` and hard `latest_finish`, but the
first authoritative barrier stays at 64 declared activities; the diagnostic
64,068 raw / 64,032 deadline-eligible placements remain above the retained
20,000-placement cap. This milestone neither schedules it nor raises any limit.

The bounded result is **A — adoption proven** when exact-head CI and review
remain green. Finish proof now dominates this admitted sample (about 73% of
batched solve wall). The next focused milestone should investigate the exact
finish proof/model-size interaction under the current admission boundary,
including whether placement representation materially causes that proof cost;
it should not automatically expand admission or placement caps. This does not establish production-scale
readiness, general workface capacity, soft deadlines, a new solver backend,
accepted-history workface correctness or a 160/120 executable plan.
