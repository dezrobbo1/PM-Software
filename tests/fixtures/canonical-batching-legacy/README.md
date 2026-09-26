# Frozen sequential-era documents

Captured **before editing the authoritative scheduler** from verified merged
`main` commit `ccd1b891dfcf68fce369c67f7d6cf2e861498041`, with Python 3.12
and pinned OR-Tools 9.15.6755. These are historical input/plan/status documents,
not regenerated fixtures from the adopted scheduler.

| Document | Historical reference plan hash |
| --- | --- |
| `small-sequential-plan.json` | `3d8409958ca0b0248d78aad631ce4e0ded7f6c6a5af15ee5c6a108121fcdc7d0` |
| `professional-sequential-plan.json` | `dea09dd2458b901faa1410c343827cc7bfd0f140ad059b1b87a47381575518bd` |
| `accepted-sequential-reference.json` | `3c7238a0c8c73a141254a08d491188cbc460cf12146e632192a375a6958da54c` |
| `rolling-sequential-cycle.json` | `64ebee72814da097951bebf95914e748266c1f788ad7225bae68434ce26f4673` |

The accepted bundle contains its serialized input, reference plan and accepted
status workspace (state hash
`f7b3539c05377c7e7e43ba58cbee9f0d91d66a75962c9e84f93b4be92042f880`).
The rolling document contains a sequential-era reference plan
and one prior promotion lineage record, including the previous hashes. The
legacy plan solver's `max_deterministic_time_per_stage` is a JSON float (`60.0`),
which is hash-significant even though it compares numerically equal to integer
`60` in Python. Fixture serialization preserves the float exactly.
