# Reference Semantic Contract `reference-v0.3`

## Purpose

This contract defines a small, explicit scheduling model for independent prototype testing. It is not presented as P6 or Microsoft Project semantics.

## Time model

- All test calculations use integer time units.
- Each fixture declares the unit, origin and horizon.
- Calendars are explicit half-open working intervals `[start, finish)`.
- An activity may execute only inside its activity calendar and all mandatory assigned-resource calendars.
- Start and finish values are integer offsets from the declared origin.
- Canonical serialisation stores timezone-aware source timestamps separately when native data are imported.

## Duration

- Duration is productive working time.
- A task's finish is obtained by consuming its duration across allowed working intervals from its scheduled start.
- A zero-duration milestone has `start == finish`.
- An activity start bound that occurs outside working time is moved to the first allowed working instant.

## Relationship formulas

Let predecessor `i` and successor `j` have start `S` and finish `F`.

- FS: `S_j >= add_lag(F_i, lag)`
- SS: `S_j >= add_lag(S_i, lag)`
- FF: `F_j >= add_lag(F_i, lag)`
- SF: `F_j >= add_lag(S_i, lag)`

For `reference-v0.3`:

- lag is consumed only on the successor activity calendar;
- positive lag adds productive working time;
- negative lag subtracts productive working time;
- zero lag preserves the predecessor event coordinate;
- all activities are bounded by project start unless an actual start precedes it;
- when several bounds apply, the latest feasible start governs;
- for finish-based bounds, the activity start is derived by subtracting its productive duration on its calendar;
- for an in-progress successor under `retained_logic`, a start-governed relationship is tested against `remaining_start` when that coordinate exists;
- for an in-progress successor under `progress_override`, unfinished predecessor logic may be intentionally non-governing for remaining start, as declared by the profile.

The canonical schema can preserve a non-null `lag_calendar`, but the active executable profile rejects it. Alternate lag-calendar semantics require a new profile and a direct expected-result fixture before execution. P6 and Microsoft Project lag/calendar rules are not assumed equivalent and require separate native profiles.

## Constraints included in `reference-v0.3`

- `start_no_earlier_than`
- `finish_no_earlier_than`
- fixed actual start
- fixed actual finish
- frozen start/finish within a declared frozen horizon

The canonical model can preserve `fixed_start` and `fixed_finish` constraint records, but the executable reference profile does not claim those semantics because the frozen corpus contains no direct fixture for either type. They require a later profile and direct expected-result cases before execution.

## Profile history

- `reference-v0.1` is the original preregistered profile.
- `reference-v0.2` removed untested `fixed_start` and `fixed_finish` execution claims.
- `reference-v0.3` removes untested alternate lag-calendar and cumulative-capacity execution claims.

All superseded profiles remain in `config/` for auditability. No CPM, optimiser or native result existed when v0.3 was declared.

## Actuals and status

- Actual start and actual finish are immutable historical facts.
- A completed activity uses its actual start and actual finish.
- An in-progress activity retains actual start and schedules remaining work no earlier than the status time unless a declared policy allows otherwise.
- `retained_logic`: remaining successor work waits for unfinished predecessor work.
- `progress_override`: remaining successor work may continue from status time despite unfinished predecessor logic.
- `actual_dates`: included as a native-validation case only in Phase 0; no unsupported equivalence is invented.

## Resources

The active executable profile claims only capacity-one exclusive resources because that is the only resource-capacity semantic directly represented in the frozen corpus.

- An executable reference resource has type `exclusive` and capacity `1`.
- Activity demand must not exceed that exclusive capacity at any time.
- Resource calendar availability intersects with the activity calendar.
- Equal-quality choices are resolved by the declared objective policy and stable activity-ID tie-break.

The canonical schema may preserve renewable, cumulative and non-renewable resource records. Cumulative capacity greater than one is not executable under `reference-v0.3`; it requires a new profile and direct expected-result fixtures.

## Float for reference micro-tests

Float is calculated only for simple 24x7 acyclic networks without actuals, resource constraints or date constraints:

- project finish is the maximum early finish;
- backward pass starts from project finish;
- total float is `late_start - early_start`;
- free float is the minimum successor early start minus activity early finish, or project finish minus early finish for a terminal activity.

No claim is made that this restricted float profile matches every native product configuration.

## Unsupported or unresolved semantics

The following require later, separate profiles:

- explicit alternate relationship-lag calendars;
- cumulative or renewable resource-capacity semantics beyond one exclusive unit;
- P6 retained-logic, progress-override and actual-dates parity beyond declared cases;
- P6 relationship-lag calendar options;
- canonical `fixed_start` and `fixed_finish` execution semantics;
- Microsoft manual task scheduling;
- native duration-type semantics;
- resource-dependent activity/task types;
- summary and level-of-effort semantics;
- suspend/resume behaviour;
- multiple float paths;
- cross-project relationships;
- full constraint hierarchies.

Any unexplained native difference is a failed compatibility claim, not a reason to modify the reference result after the fact.
