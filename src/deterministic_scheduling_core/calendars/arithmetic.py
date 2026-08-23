from __future__ import annotations

from collections.abc import Sequence


Intervals = tuple[tuple[int, int], ...]


def intersect_intervals(left: Sequence[Sequence[int]], right: Sequence[Sequence[int]]) -> Intervals:
    result: list[tuple[int, int]] = []
    left_index = right_index = 0
    while left_index < len(left) and right_index < len(right):
        start = max(left[left_index][0], right[right_index][0])
        finish = min(left[left_index][1], right[right_index][1])
        if start < finish:
            result.append((start, finish))
        if left[left_index][1] <= right[right_index][1]:
            left_index += 1
        else:
            right_index += 1
    return tuple(result)


def contains_coordinate(coordinate: int, intervals: Sequence[Sequence[int]]) -> bool:
    return any(start <= coordinate < finish for start, finish in intervals)


def consume_duration(
    start: int, duration: int, intervals: Sequence[Sequence[int]]
) -> int | None:
    """Consume productive integer duration from an explicit start coordinate."""

    if duration < 0:
        return None
    if duration == 0:
        return start if contains_coordinate(start, intervals) else None
    if not contains_coordinate(start, intervals):
        return None
    remaining = duration
    cursor = start
    for interval_start, interval_finish in intervals:
        if interval_finish <= cursor:
            continue
        if cursor < interval_start:
            cursor = interval_start
        available = interval_finish - cursor
        if remaining <= available:
            return cursor + remaining
        remaining -= available
        cursor = interval_finish
    return None


def shift_working_time(
    anchor: int, lag: int, intervals: Sequence[Sequence[int]]
) -> int | None:
    """Apply signed productive lag; zero lag preserves its event coordinate."""

    if lag == 0:
        return anchor
    if lag > 0:
        remaining = lag
        cursor = anchor
        for interval_start, interval_finish in intervals:
            if interval_finish <= cursor:
                continue
            position = max(cursor, interval_start)
            available = interval_finish - position
            if remaining <= available:
                return position + remaining
            remaining -= available
            cursor = interval_finish
        return None

    remaining = -lag
    cursor = anchor
    for interval_start, interval_finish in reversed(intervals):
        if interval_start >= cursor:
            continue
        position = min(cursor, interval_finish)
        available = position - interval_start
        if remaining <= available:
            return position - remaining
        remaining -= available
        cursor = interval_start
    return None


def earliest_span(
    start_lower_bound: int,
    finish_lower_bound: int,
    duration: int,
    intervals: Sequence[Sequence[int]],
    horizon: int,
) -> tuple[int, int] | None:
    """Return the lexicographically earliest supported productive span."""

    for candidate_start in range(max(0, start_lower_bound), horizon + 1):
        candidate_finish = consume_duration(candidate_start, duration, intervals)
        if (
            candidate_finish is not None
            and candidate_finish <= horizon
            and candidate_finish >= finish_lower_bound
        ):
            return candidate_start, candidate_finish
    return None


def productive_segments(
    start: int, finish: int, intervals: Sequence[Sequence[int]]
) -> tuple[tuple[int, int], ...]:
    segments: list[tuple[int, int]] = []
    for interval_start, interval_finish in intervals:
        segment_start = max(start, interval_start)
        segment_finish = min(finish, interval_finish)
        if segment_start < segment_finish:
            segments.append((segment_start, segment_finish))
    return tuple(segments)
