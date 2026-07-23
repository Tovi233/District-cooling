"""Heuristic initial-state helpers for building RC simulations."""

from __future__ import annotations

from typing import Any, Sequence


DEFAULT_THERMAL_MASS_OFFSETS = (
    {"start_hour": 0.0, "offset_c": 0.2},
    {"start_hour": 6.0, "offset_c": 0.5},
    {"start_hour": 10.0, "offset_c": 1.0},
    {"start_hour": 14.0, "offset_c": 1.8},
    {"start_hour": 19.0, "offset_c": 1.0},
    {"start_hour": 24.0, "offset_c": 0.2},
)


def heuristic_thermal_mass_initial_temperature_c(
    indoor_air_temperature_c: float,
    clock_hour: float,
    config: dict[str, Any] | None = None,
) -> float:
    """Estimate initial T_m from first indoor temperature and local clock hour."""
    config = config or {}
    offsets = config.get("clock_hour_offsets", DEFAULT_THERMAL_MASS_OFFSETS)
    offset_c = _piecewise_linear_offset(clock_hour % 24.0, offsets)
    minimum_offset_c = float(config.get("minimum_offset_c", -2.0))
    maximum_offset_c = float(config.get("maximum_offset_c", 3.0))
    offset_c = min(max(offset_c, minimum_offset_c), maximum_offset_c)
    return indoor_air_temperature_c + offset_c


def _piecewise_linear_offset(
    clock_hour: float,
    offsets: Sequence[dict[str, float]],
) -> float:
    if not offsets:
        return 0.0
    points = sorted(
        (float(point["start_hour"]), float(point["offset_c"]))
        for point in offsets
    )
    if clock_hour <= points[0][0]:
        return points[0][1]
    for (left_hour, left_offset), (right_hour, right_offset) in zip(
        points[:-1],
        points[1:],
    ):
        if left_hour <= clock_hour <= right_hour:
            if right_hour == left_hour:
                return right_offset
            ratio = (clock_hour - left_hour) / (right_hour - left_hour)
            return left_offset + ratio * (right_offset - left_offset)
    return points[-1][1]
