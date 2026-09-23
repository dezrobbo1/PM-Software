# Headless rolling status advancement

This bounded capability extends the accepted-progress v2 profile from one
status point to a repeated headless cycle without adding browser or server
semantics.

The engine question is:

> Can an approved recovery become the reference plan for the next status cycle,
> while accepted history remains immutable and only explicitly reviewed new
> execution/forecast facts alter the next recovery?

## Transaction

`advance_status_point(...)` is an explicit trusted-state transaction.

Given an already complete v2 status:

1. the new status point must move forward;
2. every activity that was not already `COMPLETED` must be explicitly
   re-attested;
3. previously completed assertions carry forward unchanged;
4. a prior `IN_PROGRESS` assertion may remain in progress or become completed,
   but cannot return to `NOT_STARTED`;
5. begun mode, accepted named assignments, actual start and all previously
   accepted productive periods are immutable;
6. new productive periods may only append after the prior status point;
7. remaining productive work is supplied again as an independently reviewed
   forecast assumption;
8. the prior approved plan is retained but becomes stale;
9. calculation remains a separate action, and approval remains a separate
   action.

The transition is atomic. The workspace never exposes a trusted intermediate
state in which the status point has moved but old open assertions are still
being interpreted as current.

## First bounded context rule

The existing v2 assertion captures one historical execution-context snapshot.
That is sufficient for the first rolling experiment only while a begun
activity's captured calendars, named resources, groups and accepted named
outages remain unchanged across the status boundary.

If that context changes, `advance_status_point` rejects the transaction rather
than silently validating later history against the wrong context.

Supporting rolling history across changing historical calendar/outage contexts
would need an explicit additional representation; it is not inferred in this
milestone.

## Executable control

The experiment uses the existing eight-activity native demo.

At T1, tick 22:

- A03 is `IN_PROGRESS` in `SPECIALIST` mode;
- accepted actual productive period is `[20,22)`;
- accepted remainder is 4 ticks;
- recovery finishes at tick 30.

At T2, tick 23:

- one additional productive tick becomes accepted history;
- A03 actual periods are `[20,22)`, `[22,23)`;
- accepted remainder is 3 ticks;
- the approved finish remains tick 30.

At T3, tick 25:

- another productive tick becomes accepted history before the lunch gap;
- A03 actual periods are `[20,22)`, `[22,23)`, `[23,24)`;
- the independently reviewed remainder is still 3 ticks rather than being
  automatically reduced to 2;
- A03 forecasts `[25,28)`;
- A04 moves to `[28,30)`;
- A08 moves to `[30,31)`;
- the controlling finish moves to tick 31.

This proves that accepted history can advance without being rewritten, while a
new remaining-work estimate can legitimately change the future forecast.

## Evidence boundary

This is headless engine evidence only.

It does not add:

- a rolling-status browser workflow;
- a new workspace schema;
- automatic inference of activity status;
- changed-context historical segments;
- arbitrary corrections during advancement;
- Work-Method structural choice;
- a new objective policy;
- adaptive repair;
- event sourcing.

Corrections to already accepted history remain a separate explicit operation.
