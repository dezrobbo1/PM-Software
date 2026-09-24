# Converged Native Scale Falsification v0

## Question

Can the converged native headless path preserve its already-demonstrated
structural, productive-time, physical-allocation, accepted-history and rolling
status semantics on a materially larger case without changing those semantics
merely to make the case pass?

This is a bounded falsification experiment, not a production benchmark.

## Fixture

The retained scale case contains:

- **64 declared activities**;
- **48 active activities** in the baseline selected structure;
- **8 Work Packages**;
- **4 flexible Work Packages**;
- **16 authorised structural combinations**;
- one bounded activity-mode decision;
- a productive `SHIFT` calendar with explicit non-working gaps;
- named mechanical, QA and crane resources;
- a disjoint interchangeable `RIGGING` resource group;
- accepted completed and in-progress execution history;
- one accepted `C04` outage;
- structural recovery;
- structural handover;
- one subsequent rolling status advancement.

The fixture is intentionally serial at package level. That makes it possible to
retain an independent structural/productive-time control without creating a
second large CP-SAT implementation.

## Admission change

The prior Work-Method/productive-time composition admitted at most 32 declared
activities. This experiment reaches exactly 64 declared activities, so the
bounded admission limit is changed from `1..32` to `1..64`.

The limit remains explicit. A regression proves 65 declared activities are still
rejected.

No other scale limit is raised:

- horizon remains at most 480 ticks;
- authorised structures remain at most 16;
- placement alternatives remain capped at 20,000;
- each lexicographic stage retains the existing deterministic-work budget.

The fixture is therefore evidence for one larger bounded profile, not permission
to remove the other guards.

## Independent control

The control is a fixture-specific pure-Python serial oracle.

For every authorised structural combination and permitted mode combination, it:

1. walks the selected package/activity chain in execution order;
2. derives productive ticks directly from declared calendars;
3. removes ticks covered by accepted named-resource outages;
4. respects the accepted method locks and explicit remaining work when status is
   present;
5. computes the earliest executable productive periods;
6. ranks the resulting alternatives using the same declared policy dimensions.

The oracle does **not** call CP-SAT, `schedule_work_method_time(...)`, the
candidate placement compiler, or the accepted-progress proposal solver.

Because the fixture is deliberately serial, no simultaneous resource competition
needs to be solved inside the oracle. The candidate still goes through its normal
whole-plan physical-allocation validators.

## Baseline

The native candidate selects:

- `WP01=FIXED`
- `WP02=CRANE`
- `WP03=FIXED`
- `WP04=CRANE`
- `WP05=FIXED`
- `WP06=CRANE`
- `WP07=CRANE`
- `WP08=FIXED`

Controlling objective: `[135, 138939]`.

The candidate matches the independent serial oracle on structural choice and
objective policy and repeats to the same plan. All candidate solver stages report
`OPTIMAL`.

Observed candidate metrics on the retained GitHub runner:

- placement alternatives: **9,740**
- variables: **9,945**
- constraints: **11,590**
- solver stages/calls: **138**
- model build: about **204 ms**
- solver time: about **52.6 s**
- end-to-end: about **52.8 s**

These times are observations from this source-bound evidence run, not production
performance claims.

## Accepted-history recovery

At the first status point:

- **11** activities have accepted execution history;
- one `WP02` activity is in progress with an independently revised remaining-work
  estimate;
- the already-begun `WP02=CRANE` method is hard;
- the accepted future `C04` outage affects an untouched package.

The authoritative recovery changes only `WP04: CRANE -> MANUAL` while retaining
`WP02=CRANE`.

Controlling objective: `[156, 138237]`.

The recovery matches the independent status-aware serial oracle and repeats
canonically.

Observed candidate metrics:

- fixed methods from accepted history: **2**
- placement alternatives: **8,042**
- variables: **8,234**
- constraints: **7,704**
- solver stages/calls: **130**
- solver time: about **26.3 s**
- end-to-end: about **26.5 s**

## Rolling structural status

The T1 recovery is promoted into the next active execution structure using the
existing rolling structural-status handover.

At T2:

- the newly selected `WP04=MANUAL` method has accepted execution;
- it is therefore structurally hard;
- accepted history contains **22** executed activities;
- the candidate still selects `WP04=MANUAL`;
- the independent serial oracle agrees;
- the repeated calculation is identical.

Controlling objective: `[156, 120651]`.

Observed candidate metrics:

- fixed methods from accepted history: **4**
- placement alternatives: **6,257**
- variables: **6,429**
- constraints: **3,746**
- solver stages/calls: **118**
- solver time: about **18.9 s**
- end-to-end: about **19.0 s**

The deliberately no-method-lock counterfactual happens to retain the same
structural method in this larger fixture. This scale milestone therefore does not
claim new evidence about counterfactual structural pressure; that property was
already demonstrated by the smaller PR #37 case.

## Result

The semantic hypothesis is **not falsified** by this 64-declared / 48-active
case:

- the baseline matches an independent structural/productive-time oracle;
- every candidate solver stage is proven `OPTIMAL`;
- accepted history remains immutable;
- begun structural methods remain hard;
- an untouched package changes method under the accepted outage;
- the promoted recovery survives the next rolling status cycle;
- the newly begun recovery method becomes hard;
- repeated calculations are canonical in the same environment;
- source input and prior accepted history remain unchanged.

The scale experiment also exposes a material performance signal.

The baseline uses **138 sequential lexicographic solver calls** and takes roughly
**53 seconds** on the retained runner, while model construction itself is only
about **0.2 seconds**. Runtime falls as accepted history removes future decision
freedom, but still remains roughly 26 seconds at T1 and 19 seconds at T2.

That evidence points first at **canonical stage count / repeated optimality
proofs**, not model construction, as the next focused scaling question.

It does not justify immediately attempting the older 160-possible / 120-active
fixture with the same canonicalisation strategy.

## Evidence

Run:

```bash
python -m unittest tests.test_converged_scale_experiment -v
python -m deterministic_scheduling_core.converged_scale_experiment \
  --output /tmp/converged-native-scale/results.json
```

The focused workflow stores exact source SHA, Python/OR-Tools runtime metadata,
focused test log, complete result JSON and console output.

## Explicit boundary

This experiment does not prove:

- production-scale performance;
- parallel work-package resource competition at this size;
- a general decomposition strategy;
- adaptive-repair integration with the converged status path;
- the correct replacement for sequential canonical solver stages;
- the 160/120 professional-shape case;
- UI or interoperability scalability.

The next scaling experiment should isolate the cost of canonicalisation while
preserving exactly the same selected-plan semantics and validation boundary.
