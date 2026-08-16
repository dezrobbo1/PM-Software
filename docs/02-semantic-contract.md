# Reference Semantic Contract `reference-v0.1`

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

For `reference-v0.1`:

- lag is consumed on the successor activity calendar unless a fixture explicitly declares another calendar;
- positive lag adds working time;
- negative lag subtracts working time;
- all activities are bounded by project start unless an actual start precedes it;
- when several bounds apply, the latest feasible start governs;
- for finish-based bounds, the activity start is derived by subtracting its productive duration on its calendar.

P6 and Microsoft Project lag/calendar rules are not assumed equivalent and require separate native profiles.

## Constraints included in `reference-v0.1`

- `start_no_earlier_than`
- `finish_no_earlier_than`
- fixed actual start
- fixed actual finish
- frozen start/finish within a declared frozen horizon

Other native constraints remain outside the reference subset until explicitly specified.

## Actuals and status

- Actual start and actual finish are immutable historical facts.
- A completed activity uses its actual start and actual finish.
- An in-progress activity retains actual start and schedules remaining work no earlier than the status time unless a declared policy allows otherwise.
- `retained_logic`: remaining successor work waits for unfinished predecessor work.
- `progress_override`: remaining successor work may continue from status time despite unfinished predecessor logic.
- `actual_dates`: included as a native-validation case only in Phase 0; no unsupported equivalence is invented.

## Resources

- A cumulative resource has integer capacity.
- An exclusive resource has capacity one.
- Activity demand must not exceed capacity at any time.
- Resource calendar availability intersects with the activity calendar.
- Equal-quality choices are resolved by the declared objective policy and stable activity-ID tie-break.

## Float for reference micro-tests

Float is calculated only for simple 24x7 acyclic networks without actuals, resource constraints or date constraints:

- project finish is the maximum early finish;
- backward pass starts from project finish;
- total float is `late_start - early_start`;
- free float is the minimum successor early start minus activity early finish, or project finish minus early finish for a terminal activity.

No claim is made that this restricted float profile matches every native product configuration.

## Unsupported or unresolved semantics

The following require later, separate profiles:

- P6 retained-logic, progress-override and actual-dates parity beyond declared cases
- P6 relationship-lag calendar options
- Microsoft manual task scheduling
- native duration-type semantics
- resource-dependent activity/task types
- summary and level-of-effort semantics
- suspend/resume behaviour
- multiple float paths
- cross-project relationships
- full constraint hierarchies

Any unexplained native difference is a failed compatibility claim, not a reason to modify the reference result after the fact.
