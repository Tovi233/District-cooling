"""Generic fixed-step simulation helpers."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypeVar

from district_cooling.core.base import DynamicModel
from district_cooling.core.time import fixed_time_grid


StateT = TypeVar("StateT")
InputT = TypeVar("InputT")


def simulate_fixed_step(
    model: DynamicModel[StateT, InputT],
    initial_state: StateT,
    inputs: Sequence[InputT],
    step_s: float,
) -> list[tuple[float, StateT]]:
    """Simulate a dynamic model on a fixed time grid."""
    times = fixed_time_grid(step_s, len(inputs))
    state = initial_state
    results: list[tuple[float, StateT]] = []

    for time_s, current_input in zip(times, inputs):
        results.append((time_s, state))
        state = model.step(state, current_input, step_s)

    return results
