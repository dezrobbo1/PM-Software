"""Exact precedence-support pruning of original flattened placement domains.

Every surviving row keeps its original one-based activity rank. Shared-resource
and workface conflicts are relaxed, so the result is a necessary domain only.
"""
from __future__ import annotations

from dataclasses import dataclass

from deterministic_scheduling_core.project.work_method_time import materialise, method_selections

MAX_PREPROCESSING_PLACEMENTS = 100_000


def check_preprocessing_count(count):
    """Bound raw domain materialisation before union-safe pruning."""
    if count > MAX_PREPROCESSING_PLACEMENTS:
        raise ValueError("bounded W1 preprocessing supports at most 100000 raw placements")


@dataclass(frozen=True)
class RankedPlacement:
    mode: str
    rank: int
    placement: object


def _supported(project, rows):
    active = {activity["id"] for activity in project["activities"]}
    arcs = tuple((predecessor, activity["id"])
                 for activity in project["activities"]
                 for predecessor in activity.get("predecessors", ()))
    if any(predecessor not in active or child not in active for predecessor, child in arcs):
        raise AssertionError("materialised precedence references inactive activity")
    allowed = {aid: set(range(1, len(rows[aid]) + 1)) for aid in active}
    while True:
        if any(not ranks for ranks in allowed.values()):
            return {aid: set() for aid in active}
        earliest_end = {aid: min(rows[aid][rank - 1].placement.finish for rank in ranks)
                        for aid, ranks in allowed.items()}
        latest_start = {aid: max(rows[aid][rank - 1].placement.start for rank in ranks)
                        for aid, ranks in allowed.items()}
        updated = {aid: ranks.copy() for aid, ranks in allowed.items()}
        for predecessor, child in arcs:
            updated[child] = {rank for rank in updated[child]
                              if rows[child][rank - 1].placement.start >= earliest_end[predecessor]}
            updated[predecessor] = {rank for rank in updated[predecessor]
                                    if rows[predecessor][rank - 1].placement.finish <= latest_start[child]}
        if updated == allowed:
            return allowed
        allowed = updated


def union_supported_ranks(problem, rows):
    """Union the necessary FS-support fixed points over all authorised methods."""
    retained = {aid: set() for aid in rows}
    for selection in method_selections(problem):
        projection = materialise(problem, selection)["project"]
        for aid, ranks in _supported(projection, rows).items():
            retained[aid].update(ranks)
    return retained
