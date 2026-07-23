"""Time-grid helpers."""

from __future__ import annotations


def fixed_time_grid(step_s: float, steps: int) -> list[float]:
    """Return a fixed simulation time grid in seconds."""
    if step_s <= 0:
        raise ValueError("step_s must be positive")
    if steps <= 0:
        raise ValueError("steps must be positive")
    return [index * step_s for index in range(steps)]
