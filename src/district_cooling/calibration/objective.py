"""Building RC calibration objective and simulation helpers."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
import math
from pathlib import Path
from typing import Any, Sequence

from district_cooling.core import make_daily_schedule
from district_cooling.load import (
    BuildingRCInput,
    BuildingRCModel,
    BuildingRCParameters,
    BuildingRCState,
    building_parameters_from_config,
    heuristic_thermal_mass_initial_temperature_c,
    materialize_building_model_config,
)

from .parameter_space import default_multipliers


@dataclass(frozen=True)
class CalibrationMetrics:
    """Temperature-error metrics for one simulated segment."""

    row_count: int
    rmse_c: float
    mae_c: float
    bias_c: float
    nmbe_percent: float
    cv_rmse_percent: float


@dataclass(frozen=True)
class PeriodDetectionResult:
    """Detected dominant period from irregular measured time series."""

    period_h: float
    cycle_count: float
    confidence: float
    method: str
    spectral_period_h: float | None
    autocorrelation_period_h: float | None
    peak_valley_period_h: float | None


def load_measurement_rows(path: str | Path) -> list[dict[str, str]]:
    """Load normalized measured rows from CSV."""
    with Path(path).open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def project_path(project_root: str | Path, relative_path: str) -> Path:
    """Resolve a project-relative path."""
    return Path(project_root) / relative_path


def required_columns_for_run(run_config: dict[str, Any]) -> list[str]:
    """Return columns required for calibration simulation."""
    columns = run_config["columns"]
    options = run_config["model_inputs"]
    required = [
        columns["time"],
        columns["elapsed_h"],
        columns["outdoor_air_temperature_c"],
        columns["measured_indoor_temperature_c"],
        columns["water_flow_m3_h"],
        columns["supply_water_temperature_c"],
        columns["return_water_temperature_c"],
    ]
    if not options["use_measured_water_side_q_ac"]:
        required.append(columns["measured_cooling_load_kw"])
    if options["use_measured_internal_load_as_internal_load"]:
        required.append(columns["measured_internal_load_kw"])
    if options["use_measured_solar_gain"]:
        required.append(columns["measured_solar_gain_kw"])
    return [column for column in required if column]


def filter_complete_rows(
    rows: Sequence[dict[str, str]],
    run_config: dict[str, Any],
) -> tuple[list[dict[str, str]], int]:
    """Drop rows missing required values."""
    required = required_columns_for_run(run_config)
    filtered = [
        row
        for row in rows
        if all(row.get(column, "").strip() for column in required)
    ]
    return filtered, len(rows) - len(filtered)


def duration_h(rows: Sequence[dict[str, str]], elapsed_column: str) -> float:
    """Return usable data duration in hours."""
    if len(rows) < 2:
        return 0.0
    return float(rows[-1][elapsed_column]) - float(rows[0][elapsed_column])


def detect_temperature_period(
    rows: Sequence[dict[str, str]],
    elapsed_column: str,
    temperature_column: str,
    default_period_h: float = 24.0,
    min_period_h: float = 6.0,
    max_period_h: float = 48.0,
) -> PeriodDetectionResult:
    """Detect the dominant thermal period without assuming fixed sampling interval."""
    time_values, temperature_values = _time_series(rows, elapsed_column, temperature_column)
    usable_duration = time_values[-1] - time_values[0] if len(time_values) >= 2 else 0.0
    if usable_duration <= 0.0 or len(time_values) < 8:
        return _fallback_period(default_period_h, usable_duration, "insufficient_data")

    max_period = min(max_period_h, usable_duration * 0.9)
    if max_period < min_period_h:
        return _fallback_period(default_period_h, usable_duration, "too_short_for_period")

    candidate_periods = _candidate_periods(min_period_h, max_period, step_h=0.5)
    spectral_period, spectral_confidence = _spectral_period(
        time_values,
        temperature_values,
        candidate_periods,
    )
    autocorrelation_period, autocorrelation_confidence = _autocorrelation_period(
        time_values,
        temperature_values,
        candidate_periods,
    )
    peak_valley_period, peak_valley_confidence = _peak_valley_period(
        time_values,
        temperature_values,
    )

    weighted_candidates: list[tuple[float, float, str]] = []
    if spectral_period is not None:
        weighted_candidates.append((spectral_period, spectral_confidence, "spectral"))
    if autocorrelation_period is not None:
        weighted_candidates.append(
            (autocorrelation_period, autocorrelation_confidence, "autocorrelation")
        )
    if peak_valley_period is not None:
        weighted_candidates.append((peak_valley_period, peak_valley_confidence, "peak_valley"))
    if not weighted_candidates:
        return _fallback_period(default_period_h, usable_duration, "fallback")

    total_weight = sum(weight for _, weight, _ in weighted_candidates)
    if total_weight <= 0.0:
        return _fallback_period(default_period_h, usable_duration, "fallback")
    detected_period = (
        sum(period * weight for period, weight, _ in weighted_candidates)
        / total_weight
    )
    agreement = _period_agreement([period for period, _, _ in weighted_candidates])
    confidence = min(1.0, total_weight / len(weighted_candidates)) * agreement
    method = "+".join(name for _, _, name in weighted_candidates)
    return PeriodDetectionResult(
        period_h=detected_period,
        cycle_count=usable_duration / detected_period if detected_period > 0 else 0.0,
        confidence=confidence,
        method=method,
        spectral_period_h=spectral_period,
        autocorrelation_period_h=autocorrelation_period,
        peak_valley_period_h=peak_valley_period,
    )


def _fallback_period(
    default_period_h: float,
    usable_duration_h: float,
    method: str,
) -> PeriodDetectionResult:
    return PeriodDetectionResult(
        period_h=default_period_h,
        cycle_count=usable_duration_h / default_period_h if default_period_h > 0 else 0.0,
        confidence=0.0,
        method=method,
        spectral_period_h=None,
        autocorrelation_period_h=None,
        peak_valley_period_h=None,
    )


def _time_series(
    rows: Sequence[dict[str, str]],
    elapsed_column: str,
    value_column: str,
) -> tuple[list[float], list[float]]:
    values = sorted(
        (
            float(row[elapsed_column]),
            float(row[value_column]),
        )
        for row in rows
        if row.get(elapsed_column, "").strip() and row.get(value_column, "").strip()
    )
    if not values:
        return [], []
    times, series = zip(*values)
    return list(times), list(series)


def _candidate_periods(min_period_h: float, max_period_h: float, step_h: float) -> list[float]:
    periods: list[float] = []
    value = min_period_h
    while value <= max_period_h + 1.0e-9:
        periods.append(value)
        value += step_h
    return periods


def _spectral_period(
    time_values: Sequence[float],
    values: Sequence[float],
    candidate_periods: Sequence[float],
) -> tuple[float | None, float]:
    """Return dominant sinusoidal period from an irregular-time periodogram."""
    mean_value = sum(values) / len(values)
    centered = [value - mean_value for value in values]
    variance = sum(value * value for value in centered)
    if variance <= 0.0:
        return None, 0.0

    scores: list[tuple[float, float]] = []
    for period in candidate_periods:
        omega = 2.0 * math.pi / period
        cos_values = [math.cos(omega * time_value) for time_value in time_values]
        sin_values = [math.sin(omega * time_value) for time_value in time_values]
        cos_power = sum(value * basis for value, basis in zip(centered, cos_values))
        sin_power = sum(value * basis for value, basis in zip(centered, sin_values))
        basis_power = sum(c * c + s * s for c, s in zip(cos_values, sin_values))
        score = (cos_power * cos_power + sin_power * sin_power) / (variance * basis_power)
        scores.append((period, score))

    scores.sort(key=lambda item: item[1], reverse=True)
    best_period, best_score = scores[0]
    second_score = scores[1][1] if len(scores) > 1 else 0.0
    separation = max(0.0, best_score - second_score)
    confidence = max(0.0, min(1.0, best_score + separation))
    return best_period, confidence


def _autocorrelation_period(
    time_values: Sequence[float],
    values: Sequence[float],
    candidate_periods: Sequence[float],
) -> tuple[float | None, float]:
    """Return period with the strongest positive lag correlation."""
    scores: list[tuple[float, float]] = []
    for lag_h in candidate_periods:
        paired_a: list[float] = []
        paired_b: list[float] = []
        max_base_time = time_values[-1] - lag_h
        for time_value, value in zip(time_values, values):
            if time_value > max_base_time:
                break
            shifted = _linear_interpolate(time_values, values, time_value + lag_h)
            if shifted is not None:
                paired_a.append(value)
                paired_b.append(shifted)
        if len(paired_a) < 6:
            continue
        score = _correlation(paired_a, paired_b)
        if score > 0.0:
            scores.append((lag_h, score))
    if not scores:
        return None, 0.0
    scores.sort(key=lambda item: item[1], reverse=True)
    best_period, best_score = scores[0]
    return best_period, max(0.0, min(1.0, best_score))


def _peak_valley_period(
    time_values: Sequence[float],
    values: Sequence[float],
) -> tuple[float | None, float]:
    """Estimate period from repeated local maxima and minima spacing."""
    if len(time_values) < 8:
        return None, 0.0
    smoothed = _moving_average(values, window=5)
    amplitude = max(smoothed) - min(smoothed)
    if amplitude <= 0.0:
        return None, 0.0
    prominence = amplitude * 0.15
    extrema_times: list[float] = []
    for index in range(1, len(smoothed) - 1):
        current = smoothed[index]
        if (
            current >= smoothed[index - 1]
            and current > smoothed[index + 1]
            and current - min(smoothed[max(0, index - 3) : index + 4]) >= prominence
        ):
            extrema_times.append(time_values[index])
        elif (
            current <= smoothed[index - 1]
            and current < smoothed[index + 1]
            and max(smoothed[max(0, index - 3) : index + 4]) - current >= prominence
        ):
            extrema_times.append(time_values[index])
    spacings = [
        later - earlier
        for earlier, later in zip(extrema_times[:-1], extrema_times[1:])
        if later > earlier
    ]
    if len(spacings) < 2:
        return None, 0.0
    median_half_period = sorted(spacings)[len(spacings) // 2]
    period = 2.0 * median_half_period
    mean_spacing = sum(spacings) / len(spacings)
    spread = math.sqrt(
        sum((spacing - mean_spacing) ** 2 for spacing in spacings) / len(spacings)
    )
    confidence = 1.0 / (1.0 + spread / max(mean_spacing, 1.0e-9))
    return period, max(0.0, min(1.0, confidence))


def _linear_interpolate(
    time_values: Sequence[float],
    values: Sequence[float],
    target_time: float,
) -> float | None:
    if target_time < time_values[0] or target_time > time_values[-1]:
        return None
    low = 0
    high = len(time_values) - 1
    while low <= high:
        mid = (low + high) // 2
        if time_values[mid] < target_time:
            low = mid + 1
        elif time_values[mid] > target_time:
            high = mid - 1
        else:
            return values[mid]
    upper = low
    lower = upper - 1
    if lower < 0 or upper >= len(time_values):
        return None
    span = time_values[upper] - time_values[lower]
    if span <= 0.0:
        return values[lower]
    ratio = (target_time - time_values[lower]) / span
    return values[lower] + ratio * (values[upper] - values[lower])


def _correlation(a_values: Sequence[float], b_values: Sequence[float]) -> float:
    mean_a = sum(a_values) / len(a_values)
    mean_b = sum(b_values) / len(b_values)
    centered_a = [value - mean_a for value in a_values]
    centered_b = [value - mean_b for value in b_values]
    numerator = sum(a * b for a, b in zip(centered_a, centered_b))
    denominator = math.sqrt(
        sum(a * a for a in centered_a) * sum(b * b for b in centered_b)
    )
    return numerator / denominator if denominator > 0.0 else 0.0


def _moving_average(values: Sequence[float], window: int) -> list[float]:
    radius = max(1, window // 2)
    smoothed: list[float] = []
    for index in range(len(values)):
        start = max(0, index - radius)
        end = min(len(values), index + radius + 1)
        smoothed.append(sum(values[start:end]) / (end - start))
    return smoothed


def _period_agreement(periods: Sequence[float]) -> float:
    if len(periods) < 2:
        return 0.7
    mean_period = sum(periods) / len(periods)
    spread = math.sqrt(
        sum((period - mean_period) ** 2 for period in periods) / len(periods)
    )
    return 1.0 / (1.0 + spread / max(mean_period, 1.0e-9))


def split_rows_covering_min_duration(
    rows: Sequence[dict[str, str]],
    train_fraction: float,
    elapsed_column: str,
    min_train_duration_h: float,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Split rows while keeping the training segment long enough for one cycle."""
    if not 0.0 < train_fraction < 1.0:
        raise ValueError("train_fraction must be between 0 and 1")
    split_index = max(2, min(len(rows) - 1, int(len(rows) * train_fraction)))
    while (
        split_index < len(rows) - 1
        and duration_h(rows[:split_index], elapsed_column) < min_train_duration_h
    ):
        split_index += 1
    return list(rows[:split_index]), list(rows[split_index:])


def _to_float(row: dict[str, str], column: str) -> float:
    return float(row[column].strip())


def _clock_time_s(row: dict[str, str], column: str) -> float:
    timestamp = datetime.fromisoformat(row[column].strip())
    return (
        timestamp.hour * 3600.0
        + timestamp.minute * 60.0
        + timestamp.second
        + timestamp.microsecond / 1.0e6
    )


def _water_side_cooling_load_kw(
    water_flow_m3_h: float,
    supply_water_temperature_c: float,
    return_water_temperature_c: float,
    water_density_kg_per_m3: float,
    water_specific_heat_j_per_kg_k: float,
) -> float:
    mass_flow_kg_s = water_flow_m3_h * water_density_kg_per_m3 / 3600.0
    return (
        mass_flow_kg_s
        * water_specific_heat_j_per_kg_k
        * (return_water_temperature_c - supply_water_temperature_c)
        / 1000.0
    )


def initial_thermal_mass_temperature_c(
    run_config: dict[str, Any],
    first_measured_indoor: float,
    first_clock_hour: float,
    options: dict[str, Any],
    building_config: dict[str, Any],
) -> float:
    """Return configured initial T_m for measured-data simulation."""
    initial_config = run_config.get("initial_state", {})
    if initial_config.get("thermal_mass_temperature_method") == "heuristic_clock_hour":
        return heuristic_thermal_mass_initial_temperature_c(
            indoor_air_temperature_c=first_measured_indoor,
            clock_hour=first_clock_hour,
            config=initial_config.get("thermal_mass_temperature_heuristic", {}),
        )
    return (
        first_measured_indoor
        if options["initialize_thermal_mass_temperature_from_measured_indoor"]
        else building_config["initial_state"]["thermal_mass_temperature_c"]
    )


def scaled_parameters(
    base_parameters: BuildingRCParameters,
    calibration_values: dict[str, float],
) -> BuildingRCParameters:
    """Apply dimensionless multipliers or direct physical RC values."""
    k = default_multipliers()
    k.update(
        {
            name: value
            for name, value in calibration_values.items()
            if name in k
        }
    )
    return BuildingRCParameters(
        indoor_air_heat_capacity_j_per_k=(
            calibration_values.get(
                "C_indoor",
                base_parameters.indoor_air_heat_capacity_j_per_k * k["k_C_indoor"],
            )
        ),
        thermal_mass_heat_capacity_j_per_k=(
            calibration_values.get(
                "C_m",
                base_parameters.thermal_mass_heat_capacity_j_per_k * k["k_C_m"],
            )
        ),
        outwall_thermal_resistance_k_per_w=(
            calibration_values.get(
                "R_outwall",
                base_parameters.outwall_thermal_resistance_k_per_w * k["k_R_outwall"],
            )
        ),
        mass_thermal_resistance_k_per_w=(
            calibration_values.get(
                "R_m",
                base_parameters.mass_thermal_resistance_k_per_w * k["k_R_m"],
            )
        ),
    )


def structured_parameters(
    building_config: dict[str, Any],
    calibration_values: dict[str, float],
) -> BuildingRCParameters:
    """Build RC parameters from structured physical calibration variables."""
    model = materialize_building_model_config(building_config)
    derived = model["derived_geometry"]
    wall_area_m2 = float(derived["exterior_wall_area_m2"])
    floor_area_m2 = float(derived["total_floor_area_m2"])
    indoor_volume_m3 = float(derived["indoor_air_volume_m3"])
    interior_wall_volume_m3 = float(derived.get("total_interior_wall_volume_m3", 0.0))
    base_parameters = building_parameters_from_config(building_config)

    wall_thickness_m = float(calibration_values["wall_thickness_m"])
    wall_lambda = float(calibration_values["wall_lambda_w_per_m_k"])
    wall_volumetric_heat_capacity = float(
        calibration_values["wall_volumetric_heat_capacity_j_per_m3_k"]
    )
    if "indoor_object_heat_capacity_per_floor_area_j_per_m2_k" in calibration_values:
        object_heat_capacity_per_area = float(
            calibration_values[
                "indoor_object_heat_capacity_per_floor_area_j_per_m2_k"
            ]
        )
    else:
        object_heat_capacity_per_area = float(
            calibration_values[
                "thermal_mass_heat_capacity_per_floor_area_j_per_m2_k"
            ]
        )
    mass_exchange_h = float(calibration_values["mass_exchange_h_w_per_m2_k"])
    floor_slab_thickness_m = float(
        calibration_values.get("floor_slab_thickness_m", wall_thickness_m)
    )
    floor_slab_lambda = float(
        calibration_values.get("floor_slab_lambda_w_per_m_k", wall_lambda)
    )
    floor_slab_volumetric_heat_capacity = float(
        calibration_values.get(
            "floor_slab_volumetric_heat_capacity_j_per_m3_k",
            wall_volumetric_heat_capacity,
        )
    )
    indoor_air_capacity_per_volume = float(
        calibration_values.get(
            "indoor_air_effective_capacity_j_per_m3_k",
            base_parameters.indoor_air_heat_capacity_j_per_k / indoor_volume_m3,
        )
    )

    c_wall = wall_thickness_m * wall_area_m2 * wall_volumetric_heat_capacity
    c_interior_wall = interior_wall_volume_m3 * wall_volumetric_heat_capacity
    c_floor_slab = (
        floor_slab_thickness_m * floor_area_m2 * floor_slab_volumetric_heat_capacity
    )
    c_indoor_objects = object_heat_capacity_per_area * floor_area_m2
    wall_to_air_conductance_w_per_k = wall_area_m2 / (
        wall_thickness_m / (2.0 * wall_lambda) + 1.0 / mass_exchange_h
    )
    floor_to_air_conductance_w_per_k = floor_area_m2 / (
        floor_slab_thickness_m / (2.0 * floor_slab_lambda)
        + 1.0 / mass_exchange_h
    )
    return BuildingRCParameters(
        indoor_air_heat_capacity_j_per_k=(
            indoor_air_capacity_per_volume * indoor_volume_m3
        ),
        thermal_mass_heat_capacity_j_per_k=(
            c_indoor_objects + c_floor_slab + c_wall + c_interior_wall
        ),
        outwall_thermal_resistance_k_per_w=(
            wall_thickness_m / (wall_lambda * wall_area_m2)
        ),
        mass_thermal_resistance_k_per_w=1.0 / (
            wall_to_air_conductance_w_per_k + floor_to_air_conductance_w_per_k
        ),
    )


def building_parameters_for_calibration_values(
    building_config: dict[str, Any],
    calibration_values: dict[str, float],
) -> BuildingRCParameters:
    """Return RC parameters for multiplier, absolute, or structured values."""
    if "wall_thickness_m" in calibration_values:
        return structured_parameters(building_config, calibration_values)
    return scaled_parameters(
        building_parameters_from_config(building_config),
        calibration_values,
    )


def simulate_rows(
    rows: Sequence[dict[str, str]],
    run_config: dict[str, Any],
    building_config: dict[str, Any],
    multipliers: dict[str, float],
) -> list[dict[str, float | str]]:
    """Run the building RC model for one row segment."""
    columns = run_config["columns"]
    options = run_config["model_inputs"]
    max_internal_step_s = float(options.get("max_internal_step_s", 60.0))
    schedules = building_config.get("schedules", {})
    k = default_multipliers()
    k.update(
        {
            name: value
            for name, value in multipliers.items()
            if name in k
        }
    )
    internal_load_schedule = (
        make_daily_schedule(schedules["internal_load_w"])
        if options["use_building_internal_load_schedule"] and "internal_load_w" in schedules
        else None
    )
    thermal_mass_load_schedule = (
        make_daily_schedule(schedules["thermal_mass_load_w"])
        if options["use_building_thermal_mass_load_schedule"] and "thermal_mass_load_w" in schedules
        else None
    )
    solar_gain_schedule = (
        make_daily_schedule(schedules["solar_gain_w"])
        if options["use_building_solar_gain_schedule"] and "solar_gain_w" in schedules
        else None
    )

    model = BuildingRCModel(
        building_parameters_for_calibration_values(building_config, multipliers)
    )
    first_measured_indoor = _to_float(
        rows[0],
        columns["measured_indoor_temperature_c"],
    )
    state = BuildingRCState(
        indoor_air_temperature_c=(
            first_measured_indoor
            if options["initialize_indoor_temperature_from_measured_column"]
            else building_config["initial_state"]["indoor_air_temperature_c"]
        ),
        thermal_mass_temperature_c=initial_thermal_mass_temperature_c(
            run_config=run_config,
            first_measured_indoor=first_measured_indoor,
            first_clock_hour=_clock_time_s(rows[0], columns["time"]) / 3600.0,
            options=options,
            building_config=building_config,
        ),
    )

    output_rows: list[dict[str, float | str]] = []
    for index, measurement in enumerate(rows):
        time_h = _to_float(measurement, columns["elapsed_h"])
        time_s = time_h * 3600.0
        schedule_time_s = _clock_time_s(measurement, columns["time"])
        measured_cooling_kw = _to_float(measurement, columns["measured_cooling_load_kw"])
        water_side_cooling_kw = _water_side_cooling_load_kw(
            water_flow_m3_h=_to_float(measurement, columns["water_flow_m3_h"]),
            supply_water_temperature_c=_to_float(
                measurement,
                columns["supply_water_temperature_c"],
            ),
            return_water_temperature_c=_to_float(
                measurement,
                columns["return_water_temperature_c"],
            ),
            water_density_kg_per_m3=float(options["water_density_kg_per_m3"]),
            water_specific_heat_j_per_kg_k=float(
                options["water_specific_heat_j_per_kg_k"]
            ),
        )
        cooling_load_for_q_ac_kw = (
            water_side_cooling_kw
            if options["use_measured_water_side_q_ac"]
            else measured_cooling_kw
        )
        cooling_power_w = (
            max(cooling_load_for_q_ac_kw, 0.0)
            if options["clamp_negative_cooling_load_to_zero"]
            else cooling_load_for_q_ac_kw
        ) * 1000.0
        current_internal_load_w = (
            _to_float(measurement, columns["measured_internal_load_kw"]) * 1000.0
            if options["use_measured_internal_load_as_internal_load"]
            and columns.get("measured_internal_load_kw")
            else (
                internal_load_schedule(schedule_time_s)
                if internal_load_schedule is not None
                else building_config["inputs"]["internal_load_w"]
            )
        )
        current_solar_gain_w = (
            _to_float(measurement, columns["measured_solar_gain_kw"]) * 1000.0
            if options["use_measured_solar_gain"]
            and columns.get("measured_solar_gain_kw")
            else (
                solar_gain_schedule(schedule_time_s)
                if solar_gain_schedule is not None
                else building_config["inputs"].get("solar_gain_w", 0.0)
            )
        ) * k["k_solar"]
        current_thermal_mass_load_w = (
            thermal_mass_load_schedule(schedule_time_s)
            if thermal_mass_load_schedule is not None
            else building_config["inputs"].get("thermal_mass_load_w", 0.0)
        ) * k["k_thermal_mass_load"]

        inputs = BuildingRCInput(
            outdoor_air_temperature_c=_to_float(
                measurement,
                columns["outdoor_air_temperature_c"],
            ),
            internal_load_w=current_internal_load_w,
            cooling_power_w=cooling_power_w,
            solar_gain_w=current_solar_gain_w,
            thermal_mass_load_w=current_thermal_mass_load_w,
        )
        sample = model.sample(time_s, state, inputs)
        measured_indoor_c = _to_float(
            measurement,
            columns["measured_indoor_temperature_c"],
        )
        output_rows.append(
            {
                "time": measurement[columns["time"]],
                "elapsed_h": time_h,
                "measured_indoor_temperature_c": measured_indoor_c,
                "simulated_indoor_temperature_c": sample.indoor_air_temperature_c,
                "indoor_temperature_error_c": (
                    sample.indoor_air_temperature_c - measured_indoor_c
                ),
                "cooling_power_used_kw": cooling_power_w / 1000.0,
            }
        )

        if index < len(rows) - 1:
            next_time_h = _to_float(rows[index + 1], columns["elapsed_h"])
            state = _step_with_substeps(
                model,
                state,
                inputs,
                (next_time_h - time_h) * 3600.0,
                max_internal_step_s,
            )
    return output_rows


def _step_with_substeps(
    model: BuildingRCModel,
    state: BuildingRCState,
    inputs: BuildingRCInput,
    dt_s: float,
    max_internal_step_s: float,
) -> BuildingRCState:
    """Advance with smaller Euler substeps for small air-node heat capacity."""
    if max_internal_step_s <= 0.0:
        raise ValueError("max_internal_step_s must be positive")
    remaining_s = dt_s
    current_state = state
    while remaining_s > 1.0e-9:
        step_s = min(max_internal_step_s, remaining_s)
        current_state = model.step(current_state, inputs, step_s)
        remaining_s -= step_s
    return current_state


def metrics_from_rows(rows: Sequence[dict[str, float | str]]) -> CalibrationMetrics:
    """Calculate calibration metrics from simulated output rows."""
    errors = [float(row["indoor_temperature_error_c"]) for row in rows]
    measured = [float(row["measured_indoor_temperature_c"]) for row in rows]
    mean_error = sum(errors) / len(errors)
    rmse = math.sqrt(sum(error * error for error in errors) / len(errors))
    mae = sum(abs(error) for error in errors) / len(errors)
    mean_measured = sum(measured) / len(measured)
    return CalibrationMetrics(
        row_count=len(rows),
        rmse_c=rmse,
        mae_c=mae,
        bias_c=mean_error,
        nmbe_percent=-sum(errors) / (len(errors) * mean_measured) * 100.0,
        cv_rmse_percent=rmse / mean_measured * 100.0,
    )


def regularized_loss(
    output_rows: Sequence[dict[str, float | str]],
    calibration_values: dict[str, float],
    regularization_weight: float,
    reference_values: dict[str, float] | None = None,
    dynamic_options: dict[str, Any] | None = None,
) -> float:
    """Return temperature, dynamic-slope, and prior-regularization loss."""
    metrics = metrics_from_rows(output_rows)
    loss = metrics.rmse_c
    if dynamic_options:
        loss *= float(dynamic_options.get("temperature_rmse_weight", 1.0))
        cooling_on_rmse, cooling_off_rmse = slope_rmse_by_cooling_state(
            output_rows,
            cooling_on_threshold_kw=float(
                dynamic_options.get("cooling_on_threshold_kw", 1.0)
            ),
        )
        loss += (
            float(dynamic_options.get("cooling_on_slope_weight", 0.0))
            * cooling_on_rmse
        )
        loss += (
            float(dynamic_options.get("cooling_off_slope_weight", 0.0))
            * cooling_off_rmse
        )
    if not calibration_values:
        return loss
    reference_values = reference_values or {
        name: 1.0
        for name in calibration_values
    }
    penalty = math.sqrt(
        sum(
            math.log(value / reference_values[name]) ** 2
            for name, value in calibration_values.items()
        )
        / len(calibration_values)
    )
    return loss + regularization_weight * penalty


def slope_rmse_by_cooling_state(
    output_rows: Sequence[dict[str, float | str]],
    cooling_on_threshold_kw: float,
) -> tuple[float, float]:
    """Return measured-vs-simulated slope RMSE for cooling-on and cooling-off steps."""
    cooling_on_errors: list[float] = []
    cooling_off_errors: list[float] = []
    for previous, current in zip(output_rows[:-1], output_rows[1:]):
        dt_h = float(current["elapsed_h"]) - float(previous["elapsed_h"])
        if dt_h <= 0.0:
            continue
        measured_slope = (
            float(current["measured_indoor_temperature_c"])
            - float(previous["measured_indoor_temperature_c"])
        ) / dt_h
        simulated_slope = (
            float(current["simulated_indoor_temperature_c"])
            - float(previous["simulated_indoor_temperature_c"])
        ) / dt_h
        slope_error = simulated_slope - measured_slope
        average_cooling_kw = 0.5 * (
            float(previous.get("cooling_power_used_kw", 0.0))
            + float(current.get("cooling_power_used_kw", 0.0))
        )
        if average_cooling_kw >= cooling_on_threshold_kw:
            cooling_on_errors.append(slope_error)
        else:
            cooling_off_errors.append(slope_error)

    return _rmse_or_zero(cooling_on_errors), _rmse_or_zero(cooling_off_errors)


def _rmse_or_zero(values: Sequence[float]) -> float:
    """Return RMSE, or zero if a segment has no usable samples."""
    if not values:
        return 0.0
    return math.sqrt(sum(value * value for value in values) / len(values))
