"""Central plant parameter model for first-stage chiller equipment."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ChillerModeParameters:
    """Performance parameters for one chiller operating mode."""

    mode_name: str
    cooling_capacity_kw: float
    rated_motor_power_kw: float
    cop: float
    chilled_water_temperature: str
    cooling_water_temperature: str

    def validate(self) -> None:
        if self.cooling_capacity_kw <= 0:
            raise ValueError("cooling_capacity_kw must be positive")
        if self.rated_motor_power_kw <= 0:
            raise ValueError("rated_motor_power_kw must be positive")
        if self.cop <= 0:
            raise ValueError("cop must be positive")


@dataclass(frozen=True)
class ChillerUnit:
    """One chiller equipment type and its available operating modes."""

    equipment_name: str
    quantity: int
    power_supply: str
    modes: tuple[ChillerModeParameters, ...]
    service_area: str = ""

    def validate(self) -> None:
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")
        if not self.modes:
            raise ValueError("modes must not be empty")
        for mode in self.modes:
            mode.validate()

    def mode(self, mode_name: str) -> ChillerModeParameters | None:
        """Return parameters for a mode, or None if the unit cannot run it."""
        for mode in self.modes:
            if mode.mode_name == mode_name:
                return mode
        return None


@dataclass(frozen=True)
class BasicPlantParameters:
    """Fixed central plant temperatures and chiller equipment parameters."""

    supply_water_temperature_c: float
    chillers: tuple[ChillerUnit, ...]
    return_water_temperature_c: float | None = None

    def validate(self) -> None:
        if (
            self.return_water_temperature_c is not None
            and self.return_water_temperature_c < self.supply_water_temperature_c
        ):
            raise ValueError(
                "return_water_temperature_c should be greater than or equal to "
                "supply_water_temperature_c"
            )
        if not self.chillers:
            raise ValueError("chillers must not be empty")
        for chiller in self.chillers:
            chiller.validate()


@dataclass(frozen=True)
class BasicPlantOutput:
    """Current central plant output used by other modules."""

    supply_water_temperature_c: float
    return_water_temperature_c: float | None


@dataclass(frozen=True)
class ChillerModeSummary:
    """Aggregated chiller performance for one operating mode."""

    mode_name: str
    total_cooling_capacity_kw: float
    total_rated_motor_power_kw: float
    equivalent_cop: float
    active_unit_count: int


class BasicPlantModel:
    """Central plant parameter model.

    This model stores the first-stage chiller equipment parameters. It does not
    yet dispatch chillers dynamically; it provides fixed supply/return
    temperatures and mode-level equipment summaries for later system coupling.
    """

    def __init__(self, parameters: BasicPlantParameters) -> None:
        parameters.validate()
        self.parameters = parameters

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "BasicPlantModel":
        """Build the plant model from a JSON-style configuration dictionary."""
        model_config = config["model"]
        chillers = []
        for chiller_config in model_config["chillers"]:
            modes = tuple(
                ChillerModeParameters(**mode_config)
                for mode_config in chiller_config["modes"]
            )
            chillers.append(
                ChillerUnit(
                    equipment_name=chiller_config["equipment_name"],
                    quantity=int(chiller_config["quantity"]),
                    power_supply=chiller_config["power_supply"],
                    service_area=chiller_config.get("service_area", ""),
                    modes=modes,
                )
            )

        parameters = BasicPlantParameters(
            supply_water_temperature_c=float(
                model_config["supply_water_temperature_c"]
            ),
            return_water_temperature_c=(
                float(model_config["return_water_temperature_c"])
                if "return_water_temperature_c" in model_config
                else None
            ),
            chillers=tuple(chillers),
        )
        return cls(parameters)

    def output(self) -> BasicPlantOutput:
        """Return the current fixed plant supply/return temperatures."""
        return BasicPlantOutput(
            supply_water_temperature_c=self.parameters.supply_water_temperature_c,
            return_water_temperature_c=self.parameters.return_water_temperature_c,
        )

    def summarize_mode(self, mode_name: str) -> ChillerModeSummary:
        """Aggregate all chillers that can operate in the requested mode."""
        total_capacity = 0.0
        total_power = 0.0
        active_units = 0

        for chiller in self.parameters.chillers:
            mode = chiller.mode(mode_name)
            if mode is None:
                continue
            total_capacity += chiller.quantity * mode.cooling_capacity_kw
            total_power += chiller.quantity * mode.rated_motor_power_kw
            active_units += chiller.quantity

        if total_power <= 0:
            raise ValueError(f"no chillers support mode: {mode_name}")

        return ChillerModeSummary(
            mode_name=mode_name,
            total_cooling_capacity_kw=total_capacity,
            total_rated_motor_power_kw=total_power,
            equivalent_cop=total_capacity / total_power,
            active_unit_count=active_units,
        )
