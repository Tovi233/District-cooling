"""Parameter-space rules for conservative building RC calibration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CalibrationParameter:
    """One positive parameter to be identified from measurements."""

    name: str
    lower: float
    upper: float
    initial: float = 1.0

    def validate(self) -> None:
        if self.lower <= 0:
            raise ValueError(f"{self.name} lower bound must be positive")
        if self.upper <= self.lower:
            raise ValueError(f"{self.name} upper bound must exceed lower bound")
        if not self.lower <= self.initial <= self.upper:
            raise ValueError(f"{self.name} initial value must be inside bounds")


DEFAULT_PARAMETER_LIBRARY: dict[str, CalibrationParameter] = {
    "k_R_outwall": CalibrationParameter("k_R_outwall", 0.5, 3.0),
    "k_R_m": CalibrationParameter("k_R_m", 0.5, 5.0),
    "k_C_indoor": CalibrationParameter("k_C_indoor", 0.7, 2.0),
    "k_C_m": CalibrationParameter("k_C_m", 0.3, 3.0),
    "k_solar": CalibrationParameter("k_solar", 0.0 + 1.0e-6, 2.0),
    "k_thermal_mass_load": CalibrationParameter("k_thermal_mass_load", 0.2, 3.0),
}


LEVEL_PARAMETER_NAMES = {
    0: (),
    1: ("k_R_outwall",),
    2: ("k_R_outwall", "k_C_m"),
    3: ("k_R_outwall", "k_R_m", "k_C_m", "k_solar"),
    4: (
        "k_R_outwall",
        "k_R_m",
        "k_C_indoor",
        "k_C_m",
        "k_solar",
        "k_thermal_mass_load",
    ),
}


def recommended_level(duration_h: float, requested_max_level: int = 3) -> int:
    """Return a conservative calibration level based on usable data duration."""
    if duration_h < 24.0:
        level = 1
    elif duration_h < 72.0:
        level = 2
    else:
        level = 3
    return min(level, requested_max_level)


def parameters_for_level(
    level: int,
    overrides: dict[str, Any] | None = None,
) -> list[CalibrationParameter]:
    """Return validated calibration parameters for one precision level."""
    overrides = overrides or {}
    parameters: list[CalibrationParameter] = []
    for name in LEVEL_PARAMETER_NAMES[level]:
        base = DEFAULT_PARAMETER_LIBRARY[name]
        override = overrides.get(name, {})
        parameter = CalibrationParameter(
            name=name,
            lower=float(override.get("min", base.lower)),
            upper=float(override.get("max", base.upper)),
            initial=float(override.get("initial", base.initial)),
        )
        parameter.validate()
        parameters.append(parameter)
    return parameters


def parameters_from_config(config: dict[str, Any]) -> list[CalibrationParameter]:
    """Return explicit physical parameters from a calibration configuration."""
    parameters = []
    for name, values in config.items():
        parameter = CalibrationParameter(
            name=name,
            lower=float(values["min"]),
            upper=float(values["max"]),
            initial=float(values["initial"]),
        )
        parameter.validate()
        parameters.append(parameter)
    if not parameters:
        raise ValueError("at least one calibration parameter is required")
    return parameters


def default_multipliers() -> dict[str, float]:
    """Return neutral values for all supported multipliers."""
    return {name: 1.0 for name in DEFAULT_PARAMETER_LIBRARY}
