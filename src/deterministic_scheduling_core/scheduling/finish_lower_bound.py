"""Admissible precedence-only lower bound for bounded Work-Method finish."""
from __future__ import annotations

from deterministic_scheduling_core.project.work_method_time import materialise, method_selections


def authorised_precedence_lower_bound(problem):
    """Return the earliest relaxed objective finish across every authorised structure.

    Every active activity finishes no earlier than its not-before, every
    predecessor's relaxed finish, plus its shortest authorised productive work.
    Dropping calendars and joint resource/workface contention can only advance
    those finishes, so their minimum across structures never exceeds a feasible
    joint finish. No selected plan or solver result enters this calculation.
    """
    objective = problem.project["objective_activity_id"]
    best = None
    structures = 0
    for selected in method_selections(problem):
        structures += 1
        active = materialise(problem, selected)["project"]["activities"]
        by_id = {activity["id"]: activity for activity in active}
        ends = {}
        visiting = set()

        def finish(aid):
            if aid in ends:
                return ends[aid]
            if aid in visiting:
                raise AssertionError("validated project contains a precedence cycle")
            visiting.add(aid)
            activity = by_id[aid]
            ready = max([activity.get("not_before", 0)] +
                        [finish(pid) for pid in activity.get("predecessors", [])])
            value = ready + min(mode["processing_ticks"] for mode in activity["modes"])
            visiting.remove(aid)
            ends[aid] = value
            return value

        value = finish(objective)
        best = value if best is None else min(best, value)
    if best is None:
        raise AssertionError("validated project has no authorised structure")
    return best, structures
