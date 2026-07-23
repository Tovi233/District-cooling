"""Base interfaces for dynamic RC model components."""

from __future__ import annotations

from typing import Protocol, TypeVar


StateT = TypeVar("StateT")
InputT = TypeVar("InputT")


class DynamicModel(Protocol[StateT, InputT]):
    """Minimal interface implemented by dynamic simulation components."""

    def derivative(self, state: StateT, inputs: InputT) -> StateT:
        """Return the state derivative."""

    def step(self, state: StateT, inputs: InputT, dt_s: float) -> StateT:
        """Advance the model by one time step."""
