"""Supply and return pipe-network pair for system coupling."""

from __future__ import annotations

from dataclasses import dataclass

from .pipe_rc import PipeRCInput, PipeRCModel, PipeRCParameters, PipeRCSample, PipeRCState


@dataclass(frozen=True)
class PipePairState:
    """Dynamic states of supply and return pipe water nodes."""

    supply: PipeRCState
    return_: PipeRCState


@dataclass(frozen=True)
class PipePairInput:
    """External inputs for supply and return pipe networks."""

    supply_inlet_temperature_c: float
    return_inlet_temperature_c: float
    soil_temperature_c: float
    mass_flow_kg_per_s: float


@dataclass(frozen=True)
class PipePairSample:
    """One output row for the coupled supply/return pipes."""

    time_s: float
    supply_water_temperature_c: float
    return_water_temperature_c: float
    supply_inlet_temperature_c: float
    return_inlet_temperature_c: float
    mass_flow_kg_per_s: float
    supply_pipe_heat_gain_w: float
    return_pipe_heat_gain_w: float
    terminal_cooling_power_w: float


class SupplyReturnPipeNetwork:
    """Two identical RC pipe models: one supply pipe and one return pipe."""

    def __init__(self, parameters: PipeRCParameters) -> None:
        self.supply_model = PipeRCModel(parameters)
        self.return_model = PipeRCModel(parameters)
        self.parameters = parameters

    def terminal_cooling_power_w(self, state: PipePairState, inputs: PipePairInput) -> float:
        """Cooling delivered at terminal side from return/supply temperature lift."""
        if inputs.mass_flow_kg_per_s < 0:
            raise ValueError("mass_flow_kg_per_s must be non-negative")
        return max(
            inputs.mass_flow_kg_per_s
            * self.parameters.water_specific_heat_j_per_kg_k
            * (
                state.return_.water_temperature_c
                - state.supply.water_temperature_c
            ),
            0.0,
        )

    def step(
        self,
        state: PipePairState,
        inputs: PipePairInput,
        dt_s: float,
    ) -> PipePairState:
        """Advance supply and return pipe states by one time step."""
        supply_input = PipeRCInput(
            inlet_temperature_c=inputs.supply_inlet_temperature_c,
            soil_temperature_c=inputs.soil_temperature_c,
            mass_flow_kg_per_s=inputs.mass_flow_kg_per_s,
        )
        return_input = PipeRCInput(
            inlet_temperature_c=inputs.return_inlet_temperature_c,
            soil_temperature_c=inputs.soil_temperature_c,
            mass_flow_kg_per_s=inputs.mass_flow_kg_per_s,
        )
        return PipePairState(
            supply=self.supply_model.step(state.supply, supply_input, dt_s),
            return_=self.return_model.step(state.return_, return_input, dt_s),
        )

    def sample(
        self,
        time_s: float,
        state: PipePairState,
        inputs: PipePairInput,
    ) -> PipePairSample:
        """Return one output row for the current supply/return pipe states."""
        supply_input = PipeRCInput(
            inlet_temperature_c=inputs.supply_inlet_temperature_c,
            soil_temperature_c=inputs.soil_temperature_c,
            mass_flow_kg_per_s=inputs.mass_flow_kg_per_s,
        )
        return_input = PipeRCInput(
            inlet_temperature_c=inputs.return_inlet_temperature_c,
            soil_temperature_c=inputs.soil_temperature_c,
            mass_flow_kg_per_s=inputs.mass_flow_kg_per_s,
        )
        supply_sample: PipeRCSample = self.supply_model.sample(
            time_s, state.supply, supply_input
        )
        return_sample: PipeRCSample = self.return_model.sample(
            time_s, state.return_, return_input
        )
        return PipePairSample(
            time_s=time_s,
            supply_water_temperature_c=state.supply.water_temperature_c,
            return_water_temperature_c=state.return_.water_temperature_c,
            supply_inlet_temperature_c=inputs.supply_inlet_temperature_c,
            return_inlet_temperature_c=inputs.return_inlet_temperature_c,
            mass_flow_kg_per_s=inputs.mass_flow_kg_per_s,
            supply_pipe_heat_gain_w=supply_sample.q_soil_w,
            return_pipe_heat_gain_w=return_sample.q_soil_w,
            terminal_cooling_power_w=self.terminal_cooling_power_w(state, inputs),
        )
