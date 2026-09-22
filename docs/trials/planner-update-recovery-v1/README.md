# Planner Update & Recovery Trial v1

Trial ID: `planner-update-recovery-v1`

This controlled practitioner trial asks whether an experienced planner can independently take an approved plan through status, accepted history, a separately estimated remainder, future-only recovery, approval, and save/reopen. It tests the current native scheduling model; it contains no trial-only solver rule.

Use [participant-brief.md](participant-brief.md) with the hosted Preview. The participant should receive the outcome and field facts, not the maintainer oracle in [scenario-brief.md](scenario-brief.md). Record observation separately with [facilitator-observation.md](facilitator-observation.md), collect the non-persistent [questionnaire.md](questionnaire.md), and classify findings with [exit-gate.md](exit-gate.md).

The browser sends the complete workspace with each action. The server validates or calculates and returns a complete replacement; it stores no authoritative participant workspace. Multiple browser contexts are independent. Saving downloads the native JSON workspace. Refresh/navigation does not restore unsaved work.

The trial package is produced by `python tools/build_planner_update_recovery_trial_package.py --output DIRECTORY`; CI uploads the generated ZIP rather than committing a binary.
