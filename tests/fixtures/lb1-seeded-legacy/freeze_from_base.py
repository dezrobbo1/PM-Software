"""One-time source-bound S0-batched artifact freeze; never run after adoption."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess

from deterministic_scheduling_core.accepted_work_method_time_experiment import (
    build_problem as accepted_problem, build_status_workspace,
)
from deterministic_scheduling_core.converged_scale_experiment import build_problem as scale_problem
from deterministic_scheduling_core.native_work_method_time import build_problem as small_problem
from deterministic_scheduling_core.professional_workface_experiment import build_problem as professional_problem
from deterministic_scheduling_core.project.rolling_structural_status import to_document as cycle_document
from deterministic_scheduling_core.project.work_method_time import to_document
from deterministic_scheduling_core.scheduling.accepted_work_method_time import schedule_accepted_work_method_time
from deterministic_scheduling_core.scheduling.rolling_structural_status import promote_structural_recovery_to_status_cycle
from deterministic_scheduling_core.scheduling.work_method_time import schedule_work_method_time

BASE = "33e7cf32f1f64482a79d06bdf578f39cb78d3a42"
EXPECTED = {
    "small": "458a5927a645fb2eed8a8ac432c0262d2bfcf23d3ae222a4e9f32d4682569ab5",
    "professional": "61add1ea57ede769cb676aa11f93b31eb5696f8f691b22b22a38b9f146172a7d",
    "scale_64_48": "88f125d76b5cdbe4f18e14834767e964e5b29f2db21a2c839481e1399e21f63f",
}


def main():
    if subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip() != BASE:
        raise RuntimeError("refusing to generate historical fixtures after the verified base")
    root = Path(__file__).parent
    for name, problem in (("small", small_problem()),
                          ("professional", professional_problem(workface=True, deadline=True)),
                          ("scale_64_48", scale_problem())):
        plan = schedule_work_method_time(problem).plan
        if plan["plan_hash"] != EXPECTED[name]:
            raise AssertionError(f"{name} historical hash mismatch")
        (root / f"{name}-batched-plan.json").write_text(
            json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    problem = accepted_problem()
    reference = schedule_work_method_time(problem).plan
    status = build_status_workspace(problem, reference)
    bundle = {"source": to_document(problem), "reference_plan": reference, "status_workspace": status}
    (root / "accepted-batched-reference.json").write_text(
        json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    recovery = schedule_accepted_work_method_time(problem, problem, reference, status).plan
    cycle = promote_structural_recovery_to_status_cycle(
        problem, problem, reference, status, recovery,
        asserted_by="t1-planner", accepted_by="t1-acceptor",
    )
    (root / "rolling-batched-cycle.json").write_text(
        json.dumps(cycle_document(cycle), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"source_sha": BASE, "hashes": EXPECTED,
                      "accepted_reference_hash": reference["plan_hash"],
                      "rolling_reference_hash": cycle.reference_plan["plan_hash"]}, sort_keys=True))


if __name__ == "__main__":
    main()
