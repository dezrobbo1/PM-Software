# Scenario brief and verification oracle

This maintainer document is not participant coaching. The scenario is a synthetic conveyor chute-liner replacement and return-to-service plan with nine work activities and one controlling handoff milestone.

The approved plan uses a repeating 07:00–12:00 and 12:30–17:00 productive calendar. Planner-level groups are Mechanical trades (capacity 3), Operations (1), Quality inspection (1), and Electrical testing (1). Units are declared disjoint and internally interchangeable; no fictitious worker identities are created.

## Approved starting result

| ID | Activity | Productive periods |
|---|---|---|
| A01 | Isolate conveyor and establish access | D1 07:00–08:00 |
| A02 | Remove chute covers | D1 08:00–10:00 |
| A03 | Inspect chute and confirm liner scope | D1 10:00–11:00 |
| A04 | Replace chute liners | D1 11:00–12:00; 12:30–17:00; D2 07:00–07:30 |
| A05 | Repair feed skirt | D1 10:00–12:00 |
| A06 | Prepare restart test equipment | D2 07:00–09:00 |
| A07 | Refit chute covers | D2 07:30–09:30 |
| A08 | Complete final quality inspection | D2 09:30–10:30 |
| A09 | Perform functional restart test | D2 10:30–12:00 |
| A10 | Return conveyor to service | D2 12:00 milestone |

Starting controlling finish: tick 72, Day 2 12:00. Status point: tick 24, Day 1 12:00.

Accepted history is A01, A02, A03 and A05 completed at the periods above; A04 is in progress with actual `[22,24)` and seven productive hours (14 ticks) remaining. A06–A10 are not started.

## Expected recovery

A04 future work is `[25,34)` and `[62,67)`. A06 remains `[62,66)`. A07 becomes `[67,71)`, A08 `[71,72)` and `[73,74)`, A09 `[74,77)`, and A10 completes at tick 77 (Day 2 14:30).

The controlling finish moves 2.5 elapsed hours. A04 and its dependent A07–A10 chain move. Accepted A01–A05 history is fixed; A06 remains at its approved future periods. All selected modes remain `FIXED`. A04 retains Mechanical trades ×2; no anonymous unit becomes a named worker.
