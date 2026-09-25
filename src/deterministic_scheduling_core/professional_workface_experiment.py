"""Small independent control for future-only workface and protected finish."""
from __future__ import annotations

from itertools import product

from deterministic_scheduling_core.project.model import ExecutionMethod, WorkPackage
from deterministic_scheduling_core.project.work_method_time import WorkMethodTimeProject, input_hash
from deterministic_scheduling_core.scheduling.work_method_time import schedule_work_method_time


def build_problem(*, workface: bool = False, deadline: bool = False) -> WorkMethodTimeProject:
    def activity(aid, work, calendar="ALWAYS", **extra):
        return {"id": aid, "name": aid, "modes": [{"id": "FIXED", "processing_ticks": work,
                "calendar_id": calendar, "continuity": "SUSPENDABLE_AT_AVAILABILITY_GAPS",
                "requirements": ([{"id": "MECH", "pool_ids": ["MECH"],
                                  "eligible_resource_ids": ["M"]}] if aid in {"B", "C_FAST", "C_ALT"} else [])}], **extra}

    activities = [
        activity("A_FAST", 4, "DAY"),
        activity("A_ALT", 1, "DAY", not_before=6),
        activity("B", 1, not_before=2),
        activity("C_FAST", 1),
        activity("C_ALT", 2),
        activity("D", 0), activity("E", 0, predecessors=["D"]),
        activity("F", 0, predecessors=["E"]), activity("G", 0, predecessors=["F"]),
        activity("DONE", 0),
    ]
    by_id = {a["id"]: a for a in activities}
    if workface:
        for aid in ("A_FAST", "A_ALT", "B", "C_ALT"):
            by_id[aid]["exclusion_groups"] = ["WF-A"]
    if deadline:
        by_id["B"]["latest_finish"] = 3
        # Intentionally impossible only for this inactive structural alternative.
        by_id["C_ALT"]["latest_finish"] = 0
    packages = (
        WorkPackage("BUILD", "Build", (ExecutionMethod("FAST", "Fast", ("A_FAST",), "A_FAST"),
                                        ExecutionMethod("ALT", "Alternate", ("A_ALT",), "A_ALT"))),
        WorkPackage("ACCESS", "Access", (ExecutionMethod("FIXED", "Fixed", ("B",), "B"),)),
        WorkPackage("CREW", "Crew", (ExecutionMethod("FAST", "Fast", ("C_FAST",), "C_FAST"),
                                      ExecutionMethod("ALT", "Alternate", ("C_ALT",), "C_ALT"))),
        WorkPackage("CHECK", "Check", (ExecutionMethod("FIXED", "Fixed", ("D", "E", "F", "G"), "G"),), ("CREW",)),
        WorkPackage("HANDOFF", "Handoff", (ExecutionMethod("FIXED", "Fixed", ("DONE",), "DONE"),),
                    ("BUILD", "ACCESS", "CHECK")),
    )
    return WorkMethodTimeProject({
        "id": "small-professional", "name": "Envelope and protected handoff", "horizon_ticks": 8,
        "calendars": [{"id": "DAY", "daily_windows": [[0, 2], [4, 8]]},
                      {"id": "ALWAYS", "daily_windows": [[0, 48]]}],
        "resources": [{"id": "M", "capabilities": ["MECH"], "calendar_id": "ALWAYS"}],
        "activities": activities, "objective_activity_id": "DONE", "pool_riggers": False,
    }, packages)


def independent_control(problem: WorkMethodTimeProject) -> dict:
    """Enumerate raw starts, modes and structures using fixture calendar facts.

    This deliberately does not import the placement compiler, physical checker,
    scheduling candidate or its no-overlap implementation.
    """
    source = problem.project["activities"]
    by_id = {a["id"]: a for a in source}
    day = set(range(2)) | set(range(4, 8))
    options = {}
    for a in source[:5]:
        mode = a["modes"][0]
        allowed = day if mode["calendar_id"] == "DAY" else set(range(8))
        placements = []
        for start in range(a.get("not_before", 0), 9):
            if mode["processing_ticks"] and start not in allowed:
                continue
            occupied = tuple(t for t in sorted(allowed) if t >= start)[:mode["processing_ticks"]]
            if len(occupied) != mode["processing_ticks"]:
                continue
            finish = occupied[-1] + 1 if occupied else start
            if finish <= 8 and finish <= a.get("latest_finish", 8):
                placements.append((start, finish, frozenset(occupied)))
        options[a["id"]] = placements

    best = None
    for build_index, build in enumerate(("A_FAST", "A_ALT")):
        for crew_index, crew in enumerate(("C_FAST", "C_ALT")):
            for a, b, c in product(options[build], options["B"], options[crew]):
                # B and C use the one physical M throughout their execution.
                if b[2] & c[2]:
                    continue
                occupied = [(build, a), ("B", b), (crew, c)]
                if any(x[0] != y[0] and
                       set(by_id[x[0]].get("exclusion_groups", [])) & set(by_id[y[0]].get("exclusion_groups", []))
                       and x[1][0] < y[1][1] and y[1][0] < x[1][1]
                       for i, x in enumerate(occupied) for y in occupied[i + 1:]):
                    continue
                starts = {build: a[0], "B": b[0], crew: c[0]}
                starts.update({aid: c[1] for aid in ("D", "E", "F", "G")})
                starts["DONE"] = max(a[1], b[1], c[1])
                finish = starts["DONE"]
                timing = sum((i + 1) * starts.get(row["id"], 0) for i, row in enumerate(source))
                mode_indices = tuple(1 if row["id"] in starts else 0 for row in source)
                placement_indices = tuple(starts.get(row["id"], 0) for row in source)
                key = (finish, timing, (build_index, 0, crew_index, 0, 0), mode_indices, placement_indices)
                if best is None or key < best[0]:
                    best = (key, {"selected_methods": {"BUILD": ("FAST", "ALT")[build_index],
                                                      "ACCESS": "FIXED", "CREW": ("FAST", "ALT")[crew_index],
                                                      "CHECK": "FIXED", "HANDOFF": "FIXED"},
                                  "objective": [finish, timing], "starts": starts})
    if best is None:
        raise ValueError("independent control found no feasible plan")
    return best[1]


def run_experiment() -> dict:
    cases = {}
    for label, workface, deadline in (("baseline", False, False), ("workface", True, False),
                                      ("protected", True, True), ("no_workface", False, False),
                                      ("no_deadline", True, False)):
        problem = build_problem(workface=workface, deadline=deadline)
        before = input_hash(problem)
        result = schedule_work_method_time(problem)
        control = independent_control(problem)
        starts = {entry["activity_id"]: entry["start"] for entry in result.plan["entries"]}
        cases[label] = {"objective": result.plan["objective"], "methods": result.plan["selected_methods"],
                        "starts": starts, "control_matches": control == {
                            "selected_methods": result.plan["selected_methods"],
                            "objective": result.plan["objective"], "starts": starts},
                        "source_unchanged": input_hash(problem) == before,
                        "placement_alternatives": result.metrics["placement_alternatives"]}
    return cases


if __name__ == "__main__":
    import json
    print(json.dumps(run_experiment(), indent=2))
