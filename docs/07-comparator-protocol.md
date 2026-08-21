# Comparator Protocol

## Required outputs for each resource-loaded case

A. Unlevelled CPM  
B. Native default levelling  
C. Native expert-configured levelling  
D. Experienced planner manual/selective solution  
E. Deterministic optimiser  
F. Optimiser reviewed and modified by planner

The principal comparison is `E versus C and D`, not `E versus B`.

## Native run record

Record before every native calculation:

- product name, edition, version and build
- operating system
- file hash before run
- project/calendar/status settings
- relationship-lag policy
- progress/out-of-sequence policy
- levelling mode
- levelling order/priority fields
- slack/float restrictions
- splitting options
- resource calendars and capacities
- activity/task priorities
- start/data/status date
- manual edits after levelling
- file hash after save
- reopen and recalculate result

## Expert-configured baseline

An expert baseline must be prepared or reviewed by a practitioner who regularly uses that product and relevant scheduling environment. The settings and manual changes must be logged. “Expert” cannot mean only selecting a non-default menu option without justification.

## Planner baseline

The planner receives the same scope, durations, logic, calendars, resources and operational facts. Record:

- elapsed working time
- assumptions added
- constraints absent from source data
- manual sequence changes
- rejected alternatives
- final rationale

## Blind review

Where possible, reviewers receive unlabeled schedules. Ranking and acceptance are frozen before source identity is revealed.

## Fairness controls

- identical input facts
- no hidden constraints supplied only to the optimiser
- all additional optimiser data separately timed and costed
- no default-only incumbent comparison
- no selective publication of favourable cases
- failed and timed-out optimiser runs retained
- planner modifications retained as evidence rather than treated as noise
