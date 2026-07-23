"""Single-node RC model for pipe-network water temperature."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PipeRCParameters:
    """Fixed physical parameters of the pipe-network RC model."""

    water_heat_capacity_j_per_k: float
    pipe_thermal_resistance_k_per_w: float | None = None
    water_specific_heat_j_per_kg_k: float = 4180.0
    pipe_length_m: float = 1.0
    pipe_thermal_resistance_k_m_per_w: float | None = None

    def validate(self) -> None:
        if self.water_heat_capacity_j_per_k <= 0:
            raise ValueError("water_heat_capacity_j_per_k must be positive")
        if self.pipe_length_m <= 0:
            raise ValueError("pipe_length_m must be positive")
        if (
            self.pipe_thermal_resistance_k_per_w is None
            and self.pipe_thermal_resistance_k_m_per_w is None
        ):
            raise ValueError(
                "either pipe_thermal_resistance_k_per_w or "
                "pipe_thermal_resistance_k_m_per_w must be provided"
            )
        if (
            self.pipe_thermal_resistance_k_per_w is not None
            and self.pipe_thermal_resistance_k_per_w <= 0
        ):
            raise ValueError("pipe_thermal_resistance_k_per_w must be positive")
        if (
            self.pipe_thermal_resistance_k_m_per_w is not None
            and self.pipe_thermal_resistance_k_m_per_w <= 0
        ):
            raise ValueError("pipe_thermal_resistance_k_m_per_w must be positive")
        if self.water_specific_heat_j_per_kg_k <= 0:
            raise ValueError("water_specific_heat_j_per_kg_k must be positive")

    def equivalent_pipe_thermal_resistance_k_per_w(self) -> float:
        """Return the equivalent total pipe thermal resistance."""
        if self.pipe_thermal_resistance_k_m_per_w is not None:
            return self.pipe_thermal_resistance_k_m_per_w / self.pipe_length_m
        if self.pipe_thermal_resistance_k_per_w is None:
            raise ValueError("pipe thermal resistance is not configured")
        return self.pipe_thermal_resistance_k_per_w


@dataclass(frozen=True)
class PipeRCState:
    """Dynamic state: pipe-network water temperature."""

    water_temperature_c: float


@dataclass(frozen=True)
class PipeRCInput:
    """External input signals for the pipe-network RC model."""

    inlet_temperature_c: float
    soil_temperature_c: float
    mass_flow_kg_per_s: float

    def validate(self) -> None:
        if self.mass_flow_kg_per_s < 0:
            raise ValueError("mass_flow_kg_per_s must be non-negative")


@dataclass(frozen=True)
class PipeRCSample:
    """One simulated output row."""

    time_s: float
    water_temperature_c: float
    inlet_temperature_c: float
    soil_temperature_c: float
    mass_flow_kg_per_s: float
    q_flow_w: float
    q_soil_w: float
    d_water_temperature_c_per_s: float


class PipeRCModel:
    """Pipe-network RC model.

    Equation:
        Cw * dTw/dt = Q_flow + (T_soil - Tw) / R_pipe
        Q_flow = m_dot * cp * (Tin - Tw)
    """

    def __init__(self, parameters: PipeRCParameters) -> None:
        parameters.validate()
        self.parameters = parameters

    def q_flow_w(self, state: PipeRCState, inputs: PipeRCInput) -> float:
        """Heat flow from inlet-water mixing, W."""
        inputs.validate()
        return (
            inputs.mass_flow_kg_per_s
            * self.parameters.water_specific_heat_j_per_kg_k
            * (inputs.inlet_temperature_c - state.water_temperature_c)
        )

    def q_soil_w(self, state: PipeRCState, inputs: PipeRCInput) -> float:
        """Heat exchange between surrounding soil and pipe water, W."""
        return (
            inputs.soil_temperature_c - state.water_temperature_c
        ) / self.parameters.equivalent_pipe_thermal_resistance_k_per_w()

    def derivative(self, state: PipeRCState, inputs: PipeRCInput) -> PipeRCState:
        """Return dTw/dt in degC/s."""
        d_temperature = (self.q_flow_w(state, inputs) + self.q_soil_w(state, inputs)) / (
            self.parameters.water_heat_capacity_j_per_k
        )
        return PipeRCState(water_temperature_c=d_temperature)

    def step(self, state: PipeRCState, inputs: PipeRCInput, dt_s: float) -> PipeRCState:
        """Advance one explicit Euler time step."""
        if dt_s <= 0:
            raise ValueError("dt_s must be positive")
        derivative = self.derivative(state, inputs)
        return PipeRCState(
            water_temperature_c=state.water_temperature_c
            + dt_s * derivative.water_temperature_c
        )

    def sample(self, time_s: float, state: PipeRCState, inputs: PipeRCInput) -> PipeRCSample:
        """Return one output row at the current state."""
        q_flow = self.q_flow_w(state, inputs)
        q_soil = self.q_soil_w(state, inputs)
        return PipeRCSample(
            time_s=time_s,
            water_temperature_c=state.water_temperature_c,
            inlet_temperature_c=inputs.inlet_temperature_c,
            soil_temperature_c=inputs.soil_temperature_c,
            mass_flow_kg_per_s=inputs.mass_flow_kg_per_s,
            q_flow_w=q_flow,
            q_soil_w=q_soil,
            d_water_temperature_c_per_s=(q_flow + q_soil)
            / self.parameters.water_heat_capacity_j_per_k,
        )
