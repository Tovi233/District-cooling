"""Coupled plant-pipe-building system simulation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from district_cooling.load import BuildingRCInput, BuildingRCModel, BuildingRCState
from district_cooling.network import PipePairInput, PipePairState, SupplyReturnPipeNetwork
from district_cooling.plant import BasicPlantOutput


@dataclass(frozen=True)
class CoupledSystemSample:
    """One output row for the coupled plant-pipe-building simulation."""

    time_s: float
    plant_supply_temperature_c: float
    plant_return_temperature_c: float
    pipe_supply_temperature_c: float
    pipe_return_temperature_c: float
    mass_flow_kg_per_s: float
    outdoor_air_temperature_c: float
    q_cool_w: float
    q_internal_load_w: float
    q_solar_gain_w: float
    q_outwall_w: float
    q_mass_to_air_w: float
    q_total_direct_air_w: float
    q_building_cooling_demand_w: float
    q_thermal_mass_load_w: float
    thermal_mass_heat_capacity_j_per_k: float
    calculated_building_return_temperature_c: float
    indoor_air_temperature_c: float
    thermal_mass_temperature_c: float
    supply_pipe_heat_gain_w: float
    return_pipe_heat_gain_w: float


def simulate_coupled_system(
    plant_output: BasicPlantOutput,
    pipe_network: SupplyReturnPipeNetwork,
    pipe_state: PipePairState,
    building_model: BuildingRCModel,
    building_state: BuildingRCState,
    step_s: float,
    steps: int,
    soil_temperature_c: float,
    mass_flow_kg_per_s: float,
    outdoor_air_temperature_c: float,
    internal_load_w: float,
    internal_load_schedule: Callable[[float], float] | None = None,
    solar_gain_w: float = 0.0,
    solar_gain_schedule: Callable[[float], float] | None = None,
    thermal_mass_load_w: float = 0.0,
    thermal_mass_load_schedule: Callable[[float], float] | None = None,
    thermal_mass_heat_capacity_j_per_k: float | None = None,
    thermal_mass_heat_capacity_schedule: Callable[[float], float] | None = None,
) -> list[CoupledSystemSample]:
    """Simulate the first connected plant-pipe-building chain."""
    rows: list[CoupledSystemSample] = []

    for index in range(steps):
        time_s = index * step_s
        current_internal_load_w = (
            internal_load_schedule(time_s)
            if internal_load_schedule is not None
            else internal_load_w
        )
        current_thermal_mass_load_w = (
            thermal_mass_load_schedule(time_s)
            if thermal_mass_load_schedule is not None
            else thermal_mass_load_w
        )
        current_solar_gain_w = (
            solar_gain_schedule(time_s)
            if solar_gain_schedule is not None
            else solar_gain_w
        )
        current_thermal_mass_heat_capacity = (
            thermal_mass_heat_capacity_schedule(time_s)
            if thermal_mass_heat_capacity_schedule is not None
            else thermal_mass_heat_capacity_j_per_k
        )

        supply_pipe_to_building_temperature = pipe_state.supply.water_temperature_c
        demand_input = BuildingRCInput(
            outdoor_air_temperature_c=outdoor_air_temperature_c,
            internal_load_w=current_internal_load_w,
            cooling_power_w=0.0,
            solar_gain_w=current_solar_gain_w,
            thermal_mass_load_w=current_thermal_mass_load_w,
            thermal_mass_heat_capacity_j_per_k=current_thermal_mass_heat_capacity,
        )
        q_building_cooling_demand_w = building_model.cooling_demand_w(
            building_state,
            demand_input,
        )
        calculated_building_return_temperature = (
            supply_pipe_to_building_temperature
            + q_building_cooling_demand_w
            / (
                mass_flow_kg_per_s
                * pipe_network.parameters.water_specific_heat_j_per_kg_k
            )
        )
        pipe_input = PipePairInput(
            supply_inlet_temperature_c=plant_output.supply_water_temperature_c,
            return_inlet_temperature_c=calculated_building_return_temperature,
            soil_temperature_c=soil_temperature_c,
            mass_flow_kg_per_s=mass_flow_kg_per_s,
        )
        pipe_sample = pipe_network.sample(time_s, pipe_state, pipe_input)
        q_cool_w = building_model.cooling_power_from_pipe_temperatures_w(
            supply_water_temperature_c=pipe_sample.supply_water_temperature_c,
            return_water_temperature_c=pipe_sample.return_water_temperature_c,
            mass_flow_kg_per_s=mass_flow_kg_per_s,
            water_specific_heat_j_per_kg_k=pipe_network.parameters.water_specific_heat_j_per_kg_k,
        )
        building_input = BuildingRCInput(
            outdoor_air_temperature_c=outdoor_air_temperature_c,
            internal_load_w=current_internal_load_w,
            cooling_power_w=q_cool_w,
            solar_gain_w=current_solar_gain_w,
            thermal_mass_load_w=current_thermal_mass_load_w,
            thermal_mass_heat_capacity_j_per_k=current_thermal_mass_heat_capacity,
        )
        building_sample = building_model.sample(time_s, building_state, building_input)
        rows.append(
            CoupledSystemSample(
                time_s=time_s,
                plant_supply_temperature_c=plant_output.supply_water_temperature_c,
                plant_return_temperature_c=pipe_sample.return_water_temperature_c,
                pipe_supply_temperature_c=pipe_sample.supply_water_temperature_c,
                pipe_return_temperature_c=pipe_sample.return_water_temperature_c,
                mass_flow_kg_per_s=mass_flow_kg_per_s,
                outdoor_air_temperature_c=building_sample.outdoor_air_temperature_c,
                q_cool_w=q_cool_w,
                q_internal_load_w=building_sample.internal_load_w,
                q_solar_gain_w=building_sample.solar_gain_w,
                q_outwall_w=building_sample.q_outwall_w,
                q_mass_to_air_w=building_sample.q_mass_to_air_w,
                q_total_direct_air_w=building_sample.q_total_w,
                q_building_cooling_demand_w=q_building_cooling_demand_w,
                q_thermal_mass_load_w=building_sample.thermal_mass_load_w,
                thermal_mass_heat_capacity_j_per_k=building_sample.thermal_mass_heat_capacity_j_per_k,
                calculated_building_return_temperature_c=calculated_building_return_temperature,
                indoor_air_temperature_c=building_sample.indoor_air_temperature_c,
                thermal_mass_temperature_c=building_sample.thermal_mass_temperature_c,
                supply_pipe_heat_gain_w=pipe_sample.supply_pipe_heat_gain_w,
                return_pipe_heat_gain_w=pipe_sample.return_pipe_heat_gain_w,
            )
        )
        pipe_state = pipe_network.step(pipe_state, pipe_input, step_s)
        building_state = building_model.step(building_state, building_input, step_s)

    return rows
