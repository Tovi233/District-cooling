"""System-level cooling load and pipe heat-gain calculations."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CoolingLoadBalanceInput:
    """Inputs for a simple steady cooling-load balance."""

    supply_water_temperature_c: float
    return_water_temperature_c: float
    soil_temperature_c: float
    mass_flow_kg_per_s: float
    pipe_length_m: float
    pipe_thermal_resistance_k_m_per_w: float
    water_specific_heat_j_per_kg_k: float = 4180.0

    def validate(self) -> None:
        if self.return_water_temperature_c < self.supply_water_temperature_c:
            raise ValueError(
                "return_water_temperature_c should be greater than or equal to "
                "supply_water_temperature_c"
            )
        if self.mass_flow_kg_per_s < 0:
            raise ValueError("mass_flow_kg_per_s must be non-negative")
        if self.pipe_length_m <= 0:
            raise ValueError("pipe_length_m must be positive")
        if self.pipe_thermal_resistance_k_m_per_w <= 0:
            raise ValueError("pipe_thermal_resistance_k_m_per_w must be positive")
        if self.water_specific_heat_j_per_kg_k <= 0:
            raise ValueError("water_specific_heat_j_per_kg_k must be positive")


@dataclass(frozen=True)
class CoolingLoadBalanceResult:
    """Simple cooling-load balance result."""

    terminal_cooling_load_kw: float
    pipe_heat_gain_kw: float
    plant_required_cooling_kw: float
    average_pipe_water_temperature_c: float


def calculate_load_balance(
    inputs: CoolingLoadBalanceInput,
) -> CoolingLoadBalanceResult:
    """Calculate terminal cooling load and pipe heat gain.

    Assumptions:
    - terminal load uses m_dot * cp * (T_return - T_supply)
    - pipe heat gain uses pipe length and unit-length thermal resistance:
      Q_pipe = L * (T_soil - T_avg_water) / R_pipe_per_m
    - positive pipe_heat_gain_kw means the buried pipe gains heat from soil,
      which is an extra cooling load for the plant.
    """
    inputs.validate()
    delta_t = inputs.return_water_temperature_c - inputs.supply_water_temperature_c
    terminal_load_w = (
        inputs.mass_flow_kg_per_s * inputs.water_specific_heat_j_per_kg_k * delta_t
    )
    average_water_temperature = (
        inputs.supply_water_temperature_c + inputs.return_water_temperature_c
    ) / 2
    pipe_heat_gain_w = (
        inputs.pipe_length_m
        * (inputs.soil_temperature_c - average_water_temperature)
        / inputs.pipe_thermal_resistance_k_m_per_w
    )

    return CoolingLoadBalanceResult(
        terminal_cooling_load_kw=terminal_load_w / 1000,
        pipe_heat_gain_kw=pipe_heat_gain_w / 1000,
        plant_required_cooling_kw=(terminal_load_w + pipe_heat_gain_w) / 1000,
        average_pipe_water_temperature_c=average_water_temperature,
    )
