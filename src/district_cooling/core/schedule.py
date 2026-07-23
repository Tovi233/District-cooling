"""Schedule helpers for time-varying model inputs."""

from __future__ import annotations

from collections.abc import Callable, Sequence


def make_daily_schedule(points: Sequence[dict[str, float]]) -> Callable[[float], float]:
    """Create a 24-hour repeating, linearly interpolated schedule."""
    if not points:
        raise ValueError("points must not be empty")

    sorted_points = sorted(
        (float(point["time_h"]), float(point["value"])) for point in points
    )
    if sorted_points[0][0] != 0:
        raise ValueError("daily schedule must start at time_h=0")
    for time_h, _ in sorted_points:
        if time_h < 0 or time_h > 24:
            raise ValueError("time_h must be between 0 and 24")

    if sorted_points[-1][0] < 24:
        sorted_points.append((24.0, sorted_points[0][1]))

    def value_at(time_s: float) -> float:
        hour = (time_s / 3600) % 24
        for index in range(len(sorted_points) - 1):
            left_time, left_value = sorted_points[index]
            right_time, right_value = sorted_points[index + 1]
            if left_time <= hour <= right_time:
                if right_time == left_time:
                    return right_value
                ratio = (hour - left_time) / (right_time - left_time)
                return left_value + ratio * (right_value - left_value)
        return sorted_points[-1][1]

    return value_at
