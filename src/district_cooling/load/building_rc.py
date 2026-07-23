"""Two-node RC model for building indoor air and indoor thermal mass."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .office_geometry import OfficeModule, estimate_office_interior_walls


@dataclass(frozen=True)
class BuildingRCParameters:
    """Fixed physical parameters of the building RC model."""

    indoor_air_heat_capacity_j_per_k: float
    thermal_mass_heat_capacity_j_per_k: float
    outwall_thermal_resistance_k_per_w: float
    mass_thermal_resistance_k_per_w: float

    def validate(self) -> None:
        if self.indoor_air_heat_capacity_j_per_k <= 0:
            raise ValueError("indoor_air_heat_capacity_j_per_k must be positive")
        if self.thermal_mass_heat_capacity_j_per_k <= 0:
            raise ValueError("thermal_mass_heat_capacity_j_per_k must be positive")
        if self.outwall_thermal_resistance_k_per_w <= 0:
            raise ValueError("outwall_thermal_resistance_k_per_w must be positive")
        if self.mass_thermal_resistance_k_per_w <= 0:
            raise ValueError("mass_thermal_resistance_k_per_w must be positive")


@dataclass(frozen=True)
class BuildingGeometry:
    """Basic building geometry used to derive lumped RC parameters."""

    building_count: float
    floors_per_building: float
    floor_area_per_floor_m2: float
    floor_height_m: float
    footprint_perimeter_m: float

    @property
    def total_floor_area_m2(self) -> float:
        return (
            self.building_count
            * self.floors_per_building
            * self.floor_area_per_floor_m2
        )

    @property
    def total_building_height_m(self) -> float:
        return self.floors_per_building * self.floor_height_m

    @property
    def indoor_air_volume_m3(self) -> float:
        return self.total_floor_area_m2 * self.floor_height_m

    @property
    def exterior_wall_area_m2(self) -> float:
        return (
            self.building_count
            * self.footprint_perimeter_m
            * self.total_building_height_m
        )


def building_geometry_from_config(config: dict[str, Any]) -> BuildingGeometry:
    """Return derived geometry from user-facing building dimensions."""
    building_count = float(config["building_count"])
    floors_per_building = float(config["floors_per_building"])
    floor_area_per_floor_m2 = float(
        config.get(
            "floor_area_per_floor_m2",
            float(config["total_floor_area_m2"]) / building_count / floors_per_building,
        )
    )
    floor_height_m = float(config["floor_height_m"])
    footprint_perimeter_m = float(
        config.get(
            "footprint_perimeter_m",
            4.0 * floor_area_per_floor_m2**0.5,
        )
    )
    geometry = BuildingGeometry(
        building_count=building_count,
        floors_per_building=floors_per_building,
        floor_area_per_floor_m2=floor_area_per_floor_m2,
        floor_height_m=floor_height_m,
        footprint_perimeter_m=footprint_perimeter_m,
    )
    if geometry.building_count <= 0:
        raise ValueError("building_count must be positive")
    if geometry.floors_per_building <= 0:
        raise ValueError("floors_per_building must be positive")
    if geometry.floor_area_per_floor_m2 <= 0:
        raise ValueError("floor_area_per_floor_m2 must be positive")
    if geometry.floor_height_m <= 0:
        raise ValueError("floor_height_m must be positive")
    if geometry.footprint_perimeter_m <= 0:
        raise ValueError("footprint_perimeter_m must be positive")
    return geometry


def _area_from_geometry_source(geometry: BuildingGeometry, source: str) -> float:
    if source in {"total_floor_area_m2", "floor_area_m2", "floor"}:
        return geometry.total_floor_area_m2
    if source in {"exterior_wall_area_m2", "outwall_area_m2", "wall"}:
        return geometry.exterior_wall_area_m2
    raise ValueError(f"unsupported geometry area source: {source}")


def _area_from_materialized_model(model: dict[str, Any], source: str) -> float:
    derived_geometry = model["derived_geometry"]
    if source in {"total_floor_area_m2", "floor_area_m2", "floor"}:
        return float(derived_geometry["total_floor_area_m2"])
    if source in {"exterior_wall_area_m2", "outwall_area_m2", "wall"}:
        return float(derived_geometry["exterior_wall_area_m2"])
    if source in {"interior_wall_area_m2", "inner_wall_area_m2", "partition_wall_area_m2"}:
        return float(derived_geometry["total_interior_wall_area_m2"])
    raise ValueError(f"unsupported geometry area source: {source}")


def _area_from_geometry_sources(
    geometry: BuildingGeometry,
    sources: list[str] | tuple[str, ...],
) -> float:
    area = sum(_area_from_geometry_source(geometry, source) for source in sources)
    if area <= 0:
        raise ValueError("derived heat transfer area must be positive")
    return area


def materialize_building_model_config(config: dict[str, Any]) -> dict[str, Any]:
    """Fill geometry-derived areas, volumes, and heat capacities for the RC model."""
    model = dict(config["model"])
    geometry_config = model.pop("geometry", None)
    indoor_air_config = model.pop("indoor_air", None)
    thermal_mass_heat_capacity_per_floor_area = model.pop(
        "thermal_mass_heat_capacity_per_floor_area_j_per_m2_k",
        None,
    )
    indoor_object_heat_capacity_per_floor_area = model.pop(
        "indoor_object_heat_capacity_per_floor_area_j_per_m2_k",
        None,
    )
    interior_wall_estimation_config = model.pop("interior_wall_estimation", None)
    if geometry_config is None:
        return model

    geometry = building_geometry_from_config(geometry_config)
    if indoor_air_config is not None and "indoor_air_heat_capacity_j_per_k" not in model:
        volumetric_heat_capacity = indoor_air_config.get(
            "volumetric_heat_capacity_j_per_m3_k",
            indoor_air_config.get("effective_volumetric_heat_capacity_j_per_m3_k"),
        )
        if volumetric_heat_capacity is None:
            raise ValueError(
                "indoor_air must define volumetric_heat_capacity_j_per_m3_k"
            )
        model["indoor_air_heat_capacity_j_per_k"] = (
            float(volumetric_heat_capacity)
            * geometry.indoor_air_volume_m3
        )

    base_thermal_mass_heat_capacity = 0.0
    if thermal_mass_heat_capacity_per_floor_area is not None:
        base_thermal_mass_heat_capacity += (
            float(thermal_mass_heat_capacity_per_floor_area)
            * geometry.total_floor_area_m2
        )
    if indoor_object_heat_capacity_per_floor_area is not None:
        base_thermal_mass_heat_capacity += (
            float(indoor_object_heat_capacity_per_floor_area)
            * geometry.total_floor_area_m2
        )
    if (
        base_thermal_mass_heat_capacity > 0
        and "thermal_mass_heat_capacity_j_per_k" not in model
    ):
        model["thermal_mass_heat_capacity_j_per_k"] = base_thermal_mass_heat_capacity

    if "outwall_layer" in model:
        outwall_layer = dict(model["outwall_layer"])
        outwall_layer.setdefault(
            "heat_transfer_area_m2",
            geometry.exterior_wall_area_m2,
        )
        model["outwall_layer"] = outwall_layer

    if "mass_exchange" in model:
        mass_exchange = dict(model["mass_exchange"])
        if "heat_transfer_area_m2" not in mass_exchange:
            area_sources = mass_exchange.get("heat_transfer_area_sources")
            if area_sources is None:
                mass_exchange["heat_transfer_area_m2"] = geometry.total_floor_area_m2
            else:
                mass_exchange["heat_transfer_area_m2"] = _area_from_geometry_sources(
                    geometry,
                    tuple(area_sources),
                )
        model["mass_exchange"] = mass_exchange

    derived_geometry = {
        "building_count": geometry.building_count,
        "floors_per_building": geometry.floors_per_building,
        "floor_area_per_floor_m2": geometry.floor_area_per_floor_m2,
        "floor_height_m": geometry.floor_height_m,
        "footprint_perimeter_m": geometry.footprint_perimeter_m,
        "total_building_height_m": geometry.total_building_height_m,
        "total_floor_area_m2": geometry.total_floor_area_m2,
        "indoor_air_volume_m3": geometry.indoor_air_volume_m3,
        "exterior_wall_area_m2": geometry.exterior_wall_area_m2,
    }
    if interior_wall_estimation_config is not None:
        office_module_config = interior_wall_estimation_config.get(
            "office_module",
            {},
        )
        office_module = OfficeModule(
            width_m=float(office_module_config.get("width_m", 4.95)),
            depth_m=float(office_module_config.get("depth_m", 5.70)),
        )
        estimate = estimate_office_interior_walls(
            floor_area_per_floor_m2=geometry.floor_area_per_floor_m2,
            floor_count=geometry.building_count * geometry.floors_per_building,
            floor_height_m=geometry.floor_height_m,
            wall_thickness_m=float(
                interior_wall_estimation_config.get("wall_thickness_m", 0.1)
            ),
            office_module=office_module,
            plan_aspect_ratio=float(
                interior_wall_estimation_config.get("plan_aspect_ratio", 1.0)
            ),
            layout_complexity_factor=float(
                interior_wall_estimation_config.get("layout_complexity_factor", 1.0)
            ),
        )
        derived_geometry.update(
            {
                "office_module_width_m": office_module.width_m,
                "office_module_depth_m": office_module.depth_m,
                "office_module_area_m2": office_module.area_m2,
                "estimated_office_count_per_floor": estimate.office_count_per_floor,
                "interior_wall_thickness_m": float(
                    interior_wall_estimation_config.get("wall_thickness_m", 0.1)
                ),
                "interior_wall_plan_width_m": estimate.plan_width_m,
                "interior_wall_plan_depth_m": estimate.plan_depth_m,
                "interior_wall_length_per_floor_m": estimate.interior_wall_length_per_floor_m,
                "interior_wall_area_per_floor_m2": estimate.interior_wall_area_per_floor_m2,
                "interior_wall_volume_per_floor_m3": estimate.interior_wall_volume_per_floor_m3,
                "total_interior_wall_area_m2": estimate.total_interior_wall_area_m2,
                "total_interior_wall_volume_m3": estimate.total_interior_wall_volume_m3,
            }
        )

    model["derived_geometry"] = derived_geometry

    layers = []
    for layer in model.get("thermal_mass_heat_capacity_layers", []):
        resolved_layer = dict(layer)
        if "area_m2" not in resolved_layer:
            resolved_layer["area_m2"] = _area_from_materialized_model(
                model,
                str(resolved_layer.get("area_source", "exterior_wall_area_m2")),
            )
        layers.append(resolved_layer)
    if layers:
        model["thermal_mass_heat_capacity_layers"] = layers
    return model


def thermal_resistance_from_layer(
    thickness_m: float,
    thermal_conductivity_w_per_m_k: float,
    heat_transfer_area_m2: float,
) -> float:
    """Return lumped thermal resistance R = thickness / (lambda * area)."""
    if thickness_m <= 0:
        raise ValueError("thickness_m must be positive")
    if thermal_conductivity_w_per_m_k <= 0:
        raise ValueError("thermal_conductivity_w_per_m_k must be positive")
    if heat_transfer_area_m2 <= 0:
        raise ValueError("heat_transfer_area_m2 must be positive")
    return thickness_m / (
        thermal_conductivity_w_per_m_k * heat_transfer_area_m2
    )


def thermal_resistance_from_exchange(
    heat_transfer_coefficient_w_per_m2_k: float,
    heat_transfer_area_m2: float,
) -> float:
    """Return lumped resistance R = 1 / (h * area)."""
    if heat_transfer_coefficient_w_per_m2_k <= 0:
        raise ValueError("heat_transfer_coefficient_w_per_m2_k must be positive")
    if heat_transfer_area_m2 <= 0:
        raise ValueError("heat_transfer_area_m2 must be positive")
    return 1.0 / (heat_transfer_coefficient_w_per_m2_k * heat_transfer_area_m2)


def heat_capacity_from_layer(
    thickness_m: float,
    area_m2: float,
    density_kg_per_m3: float,
    specific_heat_j_per_kg_k: float,
) -> float:
    """Return heat capacity C = thickness * area * density * specific heat."""
    if thickness_m <= 0:
        raise ValueError("thickness_m must be positive")
    if area_m2 <= 0:
        raise ValueError("area_m2 must be positive")
    if density_kg_per_m3 <= 0:
        raise ValueError("density_kg_per_m3 must be positive")
    if specific_heat_j_per_kg_k <= 0:
        raise ValueError("specific_heat_j_per_kg_k must be positive")
    return thickness_m * area_m2 * density_kg_per_m3 * specific_heat_j_per_kg_k


def building_parameters_from_config(config: dict[str, Any]) -> BuildingRCParameters:
    """Build RC parameters from direct resistance values or material layers."""
    model = materialize_building_model_config(config)
    model.pop("derived_geometry", None)
    outwall_layer = model.pop("outwall_layer", None)
    mass_layer = model.pop("mass_layer", None)
    mass_exchange = model.pop("mass_exchange", None)
    thermal_mass_heat_capacity_layers = model.pop(
        "thermal_mass_heat_capacity_layers",
        [],
    )

    if outwall_layer is not None:
        model["outwall_thermal_resistance_k_per_w"] = thermal_resistance_from_layer(
            thickness_m=float(outwall_layer["thickness_m"]),
            thermal_conductivity_w_per_m_k=float(
                outwall_layer["thermal_conductivity_w_per_m_k"]
            ),
            heat_transfer_area_m2=float(outwall_layer["heat_transfer_area_m2"]),
        )
    if mass_layer is not None:
        model["mass_thermal_resistance_k_per_w"] = thermal_resistance_from_layer(
            thickness_m=float(mass_layer["thickness_m"]),
            thermal_conductivity_w_per_m_k=float(
                mass_layer["thermal_conductivity_w_per_m_k"]
            ),
            heat_transfer_area_m2=float(mass_layer["heat_transfer_area_m2"]),
        )
    if mass_exchange is not None:
        model["mass_thermal_resistance_k_per_w"] = thermal_resistance_from_exchange(
            heat_transfer_coefficient_w_per_m2_k=float(
                mass_exchange["heat_transfer_coefficient_w_per_m2_k"]
            ),
            heat_transfer_area_m2=float(mass_exchange["heat_transfer_area_m2"]),
        )
    if thermal_mass_heat_capacity_layers:
        model["thermal_mass_heat_capacity_j_per_k"] = float(
            model["thermal_mass_heat_capacity_j_per_k"]
        ) + sum(
            heat_capacity_from_layer(
                thickness_m=float(layer["thickness_m"]),
                area_m2=float(layer["area_m2"]),
                density_kg_per_m3=float(layer["density_kg_per_m3"]),
                specific_heat_j_per_kg_k=float(layer["specific_heat_j_per_kg_k"]),
            )
            for layer in thermal_mass_heat_capacity_layers
        )

    return BuildingRCParameters(**model)


@dataclass(frozen=True)
class BuildingRCState:
    """Dynamic states of the building RC model."""

    indoor_air_temperature_c: float
    thermal_mass_temperature_c: float


@dataclass(frozen=True)
class BuildingRCInput:
    """External input signals for the building RC model."""

    outdoor_air_temperature_c: float
    internal_load_w: float
    cooling_power_w: float
    solar_gain_w: float = 0.0
    thermal_mass_load_w: float = 0.0
    thermal_mass_heat_capacity_j_per_k: float | None = None

    def validate(self) -> None:
        if self.cooling_power_w < 0:
            raise ValueError("cooling_power_w must be non-negative")
        if (
            self.thermal_mass_heat_capacity_j_per_k is not None
            and self.thermal_mass_heat_capacity_j_per_k <= 0
        ):
            raise ValueError("thermal_mass_heat_capacity_j_per_k must be positive")


@dataclass(frozen=True)
class BuildingRCSample:
    """One simulated output row."""

    time_s: float
    indoor_air_temperature_c: float
    thermal_mass_temperature_c: float
    outdoor_air_temperature_c: float
    internal_load_w: float
    solar_gain_w: float
    cooling_power_w: float
    q_total_w: float
    thermal_mass_load_w: float
    thermal_mass_heat_capacity_j_per_k: float
    q_outwall_w: float
    q_mass_to_air_w: float
    d_indoor_air_temperature_c_per_s: float
    d_thermal_mass_temperature_c_per_s: float


class BuildingRCModel:
    """Building RC model with indoor air and indoor thermal mass nodes.

    Equations:
        C_indoor * dT_indoor/dt =
            (T_outdoor - T_indoor) / R_outwall
            + (T_m - T_indoor) / R_m
            - Q_ac

        C_m * dT_m/dt =
            Q_internal + Q_m + Q_solar - (T_m - T_indoor) / R_m

    Here Q_internal is the self-generated heat source from equipment,
    occupants, and lighting. Q_solar is transmitted through windows to indoor
    objects. Both first heat the indoor thermal-mass node and then reach indoor
    air through R_m.
    """

    def __init__(self, parameters: BuildingRCParameters) -> None:
        parameters.validate()
        self.parameters = parameters

    def q_total_w(self, inputs: BuildingRCInput) -> float:
        """Net direct heat added to indoor air after cooling, W."""
        inputs.validate()
        return -inputs.cooling_power_w

    def effective_thermal_mass_heat_capacity_j_per_k(
        self,
        inputs: BuildingRCInput,
    ) -> float:
        """Return thermal mass heat capacity for the current time step."""
        inputs.validate()
        if inputs.thermal_mass_heat_capacity_j_per_k is not None:
            return inputs.thermal_mass_heat_capacity_j_per_k
        return self.parameters.thermal_mass_heat_capacity_j_per_k

    def cooling_power_from_pipe_temperatures_w(
        self,
        supply_water_temperature_c: float,
        return_water_temperature_c: float,
        mass_flow_kg_per_s: float,
        water_specific_heat_j_per_kg_k: float = 4180.0,
    ) -> float:
        """Cooling power calculated from supply and return pipe temperatures."""
        if mass_flow_kg_per_s < 0:
            raise ValueError("mass_flow_kg_per_s must be non-negative")
        if water_specific_heat_j_per_kg_k <= 0:
            raise ValueError("water_specific_heat_j_per_kg_k must be positive")
        return max(
            mass_flow_kg_per_s
            * water_specific_heat_j_per_kg_k
            * (return_water_temperature_c - supply_water_temperature_c),
            0.0,
        )

    def q_outwall_w(self, state: BuildingRCState, inputs: BuildingRCInput) -> float:
        """Heat exchange between outdoor air and indoor air, W."""
        return (
            inputs.outdoor_air_temperature_c - state.indoor_air_temperature_c
        ) / self.parameters.outwall_thermal_resistance_k_per_w

    def q_mass_to_air_w(self, state: BuildingRCState) -> float:
        """Heat exchange from indoor thermal mass to indoor air, W."""
        return (
            state.thermal_mass_temperature_c - state.indoor_air_temperature_c
        ) / self.parameters.mass_thermal_resistance_k_per_w

    def q_solar_gain_w(self, inputs: BuildingRCInput) -> float:
        """Solar heat gain transmitted through windows to indoor objects, W."""
        return inputs.solar_gain_w

    def cooling_demand_w(
        self,
        state: BuildingRCState,
        inputs: BuildingRCInput,
    ) -> float:
        """Cooling demand before the air-conditioning coil removes heat, W."""
        return max(
            self.q_outwall_w(state, inputs)
            + self.q_mass_to_air_w(state),
            0.0,
        )

    def derivative(
        self,
        state: BuildingRCState,
        inputs: BuildingRCInput,
    ) -> BuildingRCState:
        """Return dT_indoor/dt and dT_m/dt in degC/s."""
        d_indoor = (
            self.q_outwall_w(state, inputs)
            + self.q_mass_to_air_w(state)
            + self.q_total_w(inputs)
        ) / self.parameters.indoor_air_heat_capacity_j_per_k
        d_mass = (
            inputs.internal_load_w
            + inputs.thermal_mass_load_w
            + self.q_solar_gain_w(inputs)
            - self.q_mass_to_air_w(state)
        ) / self.effective_thermal_mass_heat_capacity_j_per_k(inputs)
        return BuildingRCState(
            indoor_air_temperature_c=d_indoor,
            thermal_mass_temperature_c=d_mass,
        )

    def step(
        self,
        state: BuildingRCState,
        inputs: BuildingRCInput,
        dt_s: float,
    ) -> BuildingRCState:
        """Advance one explicit Euler time step."""
        if dt_s <= 0:
            raise ValueError("dt_s must be positive")
        derivative = self.derivative(state, inputs)
        return BuildingRCState(
            indoor_air_temperature_c=state.indoor_air_temperature_c
            + dt_s * derivative.indoor_air_temperature_c,
            thermal_mass_temperature_c=state.thermal_mass_temperature_c
            + dt_s * derivative.thermal_mass_temperature_c,
        )

    def sample(
        self,
        time_s: float,
        state: BuildingRCState,
        inputs: BuildingRCInput,
    ) -> BuildingRCSample:
        """Return one output row at the current state."""
        derivative = self.derivative(state, inputs)
        return BuildingRCSample(
            time_s=time_s,
            indoor_air_temperature_c=state.indoor_air_temperature_c,
            thermal_mass_temperature_c=state.thermal_mass_temperature_c,
            outdoor_air_temperature_c=inputs.outdoor_air_temperature_c,
            internal_load_w=inputs.internal_load_w,
            solar_gain_w=inputs.solar_gain_w,
            cooling_power_w=inputs.cooling_power_w,
            q_total_w=self.q_total_w(inputs),
            thermal_mass_load_w=inputs.thermal_mass_load_w,
            thermal_mass_heat_capacity_j_per_k=self.effective_thermal_mass_heat_capacity_j_per_k(inputs),
            q_outwall_w=self.q_outwall_w(state, inputs),
            q_mass_to_air_w=self.q_mass_to_air_w(state),
            d_indoor_air_temperature_c_per_s=derivative.indoor_air_temperature_c,
            d_thermal_mass_temperature_c_per_s=derivative.thermal_mass_temperature_c,
        )
