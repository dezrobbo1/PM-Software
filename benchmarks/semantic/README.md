# Semantic Micro-Test Corpus

This directory contains exactly 50 preregistered fixtures.

## Categories

- `SEM-REL-001`–`012`: relationship type and signed lag
- `SEM-NET-013`–`020`: network convergence, divergence and driving bounds
- `SEM-CAL-021`–`030`: working-time calendars, gaps, holidays and resource availability
- `SEM-MIL/CON-031`–`038`: milestones and included date constraints
- `SEM-STA-039`–`046`: actuals, status and bounded out-of-sequence policies
- `SEM-FLT-047`–`048`: restricted float semantics
- `SEM-DET-049`–`050`: deterministic resource/objective tie-breaking

## Rules

- The fixtures define `reference-v0.1`, not P6 or Microsoft Project semantics.
- Native expectations remain `required` unless marked not applicable.
- `SEM-STA-045` intentionally has no invented reference forecast for P6 Actual Dates behaviour; it tests preservation of actual facts and requires native execution.
- Expected outputs may be changed only through Phase 0 change control.
- A later engine must not generate the expected values from the same implementation under test.
