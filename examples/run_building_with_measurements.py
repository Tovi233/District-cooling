"""Run the building RC model using imported measured data."""

from __future__ import annotations

import csv
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from PIL import Image, ImageDraw, ImageFont


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from district_cooling.core import make_daily_schedule  # noqa: E402
from district_cooling.io import load_json_config, write_dict_rows  # noqa: E402
from district_cooling.calibration.building_calibrator import _prior_rc_ranges  # noqa: E402
from district_cooling.calibration.objective import building_parameters_for_calibration_values  # noqa: E402
from district_cooling.load import BuildingRCInput, BuildingRCModel, BuildingRCState, building_parameters_from_config, heuristic_thermal_mass_initial_temperature_c  # noqa: E402
from district_cooling.load.solar_measurements import maybe_add_solar_measurements  # noqa: E402
from district_cooling.results import ResultSeriesPoint, export_series_png  # noqa: E402


DEFAULT_RUN_CONFIG_PATH = (
    SRC_DIR
    / "district_cooling"
    / "load"
    / "inputs"
    / "measurements"
    / "wzs_building_run_config.json"
)


def project_path(relative_path: str) -> Path:
    """Resolve a project-relative path from the run configuration."""
    return PROJECT_ROOT / relative_path


def load_run_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load measured-data run configuration."""
    return load_json_config(Path(path) if path is not None else DEFAULT_RUN_CONFIG_PATH)


def output_paths(config: dict[str, Any]) -> dict[str, Path]:
    """Return output paths for this measured-data run."""
    output_dir = project_path(config["output_dir"])
    return {
        "comparison_csv": output_dir / "building_measurement_comparison.csv",
        "indoor_heat_source_csv": output_dir / "indoor_heat_source_timeseries.csv",
        "metrics_json": output_dir / "building_measurement_metrics.json",
        "simulated_png": output_dir / "simulated_indoor_temperature.png",
        "measured_png": output_dir / "measured_indoor_temperature.png",
        "comparison_png": output_dir / "indoor_temperature_comparison.png",
        "cooling_load_comparison_png": output_dir / "cooling_load_comparison.png",
        "indoor_heat_source_png": output_dir / "indoor_heat_source_timeseries.png",
    }


def _to_float(row: dict[str, str], column: str) -> float:
    value = row[column].strip()
    if not value:
        raise ValueError(f"blank value in column: {column}")
    return float(value)


def _clock_time_s(row: dict[str, str], column: str) -> float:
    """Return seconds since local midnight from the measurement timestamp."""
    timestamp = datetime.fromisoformat(row[column].strip())
    return (
        timestamp.hour * 3600.0
        + timestamp.minute * 60.0
        + timestamp.second
        + timestamp.microsecond / 1.0e6
    )


def load_measurement_rows(path: str | Path) -> list[dict[str, str]]:
    """Load normalized measurement rows."""
    with Path(path).open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def _required_columns_for_run(config: dict[str, Any]) -> list[str]:
    """Return measurement columns that must be populated for this run."""
    columns = config["columns"]
    options = config["model_inputs"]
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


def _filter_complete_measurement_rows(
    rows: Sequence[dict[str, str]],
    config: dict[str, Any],
) -> tuple[list[dict[str, str]], int]:
    """Keep rows with all values required by the configured validation run."""
    required_columns = _required_columns_for_run(config)
    filtered_rows = [
        row
        for row in rows
        if all(row.get(column, "").strip() for column in required_columns)
    ]
    return filtered_rows, len(rows) - len(filtered_rows)


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def _rmse(errors: Sequence[float]) -> float:
    return math.sqrt(sum(error * error for error in errors) / len(errors))


def _nmbe_percent(errors: Sequence[float], measured_values: Sequence[float]) -> float:
    """Return NMBE using measured minus simulated sign convention."""
    return -sum(errors) / (len(errors) * _mean(measured_values)) * 100.0


def _cv_rmse_percent(errors: Sequence[float], measured_values: Sequence[float]) -> float:
    """Return CV(RMSE) normalized by the measured mean."""
    return _rmse(errors) / _mean(measured_values) * 100.0


def _plot_font(size: int = 22, bold: bool = False) -> ImageFont.ImageFont:
    """Return a larger plot font with a default fallback."""
    font_names = (
        ("arialbd.ttf", "DejaVuSans-Bold.ttf", "arial.ttf", "DejaVuSans.ttf")
        if bold
        else ("arial.ttf", "DejaVuSans.ttf")
    )
    for font_name in font_names:
        try:
            return ImageFont.truetype(font_name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _aligned_plot_x_values(rows: Sequence[dict[str, float | str]]) -> list[float]:
    """Return hours from first-day midnight, leaving pre-start time blank."""
    if not rows:
        raise ValueError("rows must not be empty")
    first_clock_hour = float(rows[0]["clock_hour"])
    return [float(row["elapsed_h"]) + first_clock_hour for row in rows]


def _x_axis_bounds(x_values: Sequence[float]) -> tuple[float, float]:
    """Return 0 to the next 24-hour multiple."""
    x_max = max(x_values)
    return 0.0, max(24.0, math.ceil(x_max / 24.0) * 24.0)


def _nice_y_bounds(y_values: Sequence[float]) -> tuple[float, float]:
    """Return padded y-axis bounds."""
    y_min = min(y_values)
    y_max = max(y_values)
    if y_max == y_min:
        return y_min - 1.0, y_max + 1.0
    padding = (y_max - y_min) * 0.08
    return y_min - padding, y_max + padding


def _draw_time_axis_ticks(
    draw: ImageDraw.ImageDraw,
    x_coord: Any,
    axis_y: float,
    plot_top: float,
    x_min: float,
    x_max: float,
    font: ImageFont.ImageFont,
) -> None:
    """Draw x-axis ticks every 24 hours."""
    tick = 0.0
    while tick <= x_max + 1.0e-9:
        x = x_coord(tick)
        draw.line((x, plot_top, x, axis_y), fill="#eeeeee", width=1)
        draw.line((x, axis_y - 5, x, axis_y + 5), fill="#222222", width=2)
        draw.text((x, axis_y + 22), f"{tick:.0f}", fill="#111111", font=font, anchor="mm")
        tick += 24.0


def _draw_y_axis_ticks(
    draw: ImageDraw.ImageDraw,
    y_coord: Any,
    plot_left: float,
    plot_right: float,
    y_min: float,
    y_max: float,
    font: ImageFont.ImageFont,
) -> None:
    """Draw y-axis ticks and horizontal grid lines."""
    tick_count = 5
    for index in range(tick_count):
        value = y_min + (y_max - y_min) * index / (tick_count - 1)
        y = y_coord(value)
        draw.line((plot_left, y, plot_right, y), fill="#eeeeee", width=1)
        draw.line((plot_left - 5, y, plot_left + 5, y), fill="#222222", width=2)
        draw.text((plot_left - 12, y), f"{value:.1f}", fill="#111111", font=font, anchor="rm")


def _draw_vertical_label(
    image: Image.Image,
    text: str,
    center: tuple[float, float],
    font: ImageFont.ImageFont,
) -> None:
    """Draw a readable vertical axis label."""
    bbox = ImageDraw.Draw(Image.new("RGB", (1, 1))).textbbox((0, 0), text, font=font)
    label_width = bbox[2] - bbox[0] + 8
    label_height = bbox[3] - bbox[1] + 8
    label = Image.new("RGBA", (label_width, label_height), (255, 255, 255, 0))
    label_draw = ImageDraw.Draw(label)
    label_draw.text((4, 4), text, fill="#111111", font=font)
    rotated = label.rotate(90, expand=True)
    x = int(center[0] - rotated.width / 2)
    y = int(center[1] - rotated.height / 2)
    image.paste(rotated, (x, y), rotated)


def _water_side_cooling_load_kw(
    water_flow_m3_h: float,
    supply_water_temperature_c: float,
    return_water_temperature_c: float,
    water_density_kg_per_m3: float,
    water_specific_heat_j_per_kg_k: float,
) -> float:
    """Calculate cooling load from measured water flow and temperatures."""
    mass_flow_kg_s = water_flow_m3_h * water_density_kg_per_m3 / 3600.0
    return (
        mass_flow_kg_s
        * water_specific_heat_j_per_kg_k
        * (return_water_temperature_c - supply_water_temperature_c)
        / 1000.0
    )


def _rc_parameter_dict(parameters: Any) -> dict[str, float]:
    """Return the RC parameters currently used by the measured-data run."""
    return {
        "R_outwall": float(parameters.outwall_thermal_resistance_k_per_w),
        "R_m": float(parameters.mass_thermal_resistance_k_per_w),
        "C_indoor": float(parameters.indoor_air_heat_capacity_j_per_k),
        "C_m": float(parameters.thermal_mass_heat_capacity_j_per_k),
    }


def _building_type_prior_messages(
    config: dict[str, Any],
    rc_parameters: dict[str, float],
) -> list[str]:
    """Compare active RC parameters with the configured building-type prior."""
    prior_config = config.get("building_type_prior")
    if not prior_config:
        return []
    prior_library = load_json_config(project_path(prior_config["path"]))
    category_key = str(prior_config["category"])
    category = prior_library["categories"][category_key]
    ranges = _prior_rc_ranges(category)
    messages = [f"Building type RC prior loaded: {category_key}."]
    outside: list[str] = []
    for name, range_values in ranges.items():
        value = rc_parameters[name]
        if value < range_values["min"] or value > range_values["max"]:
            outside.append(
                f"{name}={value:.6g} outside "
                f"[{range_values['min']:.6g}, {range_values['max']:.6g}]"
            )
    if outside:
        messages.append(
            "RC parameters outside the building-type prior range: "
            + "; ".join(outside)
            + ". Please check whether building scale, data quality, or model assumptions explain this."
        )
    else:
        messages.append("All active RC parameters are inside the building-type prior range.")
    return messages


def _initial_thermal_mass_temperature_c(
    config: dict[str, Any],
    first_measured_indoor: float,
    first_clock_hour: float,
    options: dict[str, Any],
    building_config: dict[str, Any],
) -> float:
    initial_config = config.get("initial_state", {})
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


def _building_input_from_measurement(
    measurement: dict[str, str],
    columns: dict[str, str],
    options: dict[str, Any],
    building_config: dict[str, Any],
    schedules: dict[str, Any],
    multipliers: dict[str, float],
) -> tuple[BuildingRCInput, dict[str, float]]:
    measured_cooling_kw = _to_float(measurement, columns["measured_cooling_load_kw"])
    water_flow_m3_h = _to_float(measurement, columns["water_flow_m3_h"])
    supply_water_temperature_c = _to_float(
        measurement,
        columns["supply_water_temperature_c"],
    )
    return_water_temperature_c = _to_float(
        measurement,
        columns["return_water_temperature_c"],
    )
    water_side_cooling_kw = _water_side_cooling_load_kw(
        water_flow_m3_h=water_flow_m3_h,
        supply_water_temperature_c=supply_water_temperature_c,
        return_water_temperature_c=return_water_temperature_c,
        water_density_kg_per_m3=float(options["water_density_kg_per_m3"]),
        water_specific_heat_j_per_kg_k=float(options["water_specific_heat_j_per_kg_k"]),
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
    schedule_time_s = _clock_time_s(measurement, columns["time"])
    internal_load_schedule = schedules.get("internal_load_schedule")
    solar_gain_schedule = schedules.get("solar_gain_schedule")
    thermal_mass_load_schedule = schedules.get("thermal_mass_load_schedule")
    thermal_mass_heat_capacity_schedule = schedules.get(
        "thermal_mass_heat_capacity_schedule"
    )
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
    ) * float(multipliers.get("k_solar", 1.0))
    current_thermal_mass_load_w = (
        thermal_mass_load_schedule(schedule_time_s)
        if thermal_mass_load_schedule is not None
        else building_config["inputs"].get("thermal_mass_load_w", 0.0)
    ) * float(multipliers.get("k_thermal_mass_load", 1.0))
    current_thermal_mass_heat_capacity = (
        thermal_mass_heat_capacity_schedule(schedule_time_s)
        if thermal_mass_heat_capacity_schedule is not None
        else None
    )
    inputs = BuildingRCInput(
        outdoor_air_temperature_c=_to_float(
            measurement,
            columns["outdoor_air_temperature_c"],
        ),
        internal_load_w=current_internal_load_w,
        cooling_power_w=cooling_power_w,
        solar_gain_w=current_solar_gain_w,
        thermal_mass_load_w=current_thermal_mass_load_w,
        thermal_mass_heat_capacity_j_per_k=current_thermal_mass_heat_capacity,
    )
    diagnostics = {
        "measured_cooling_kw": measured_cooling_kw,
        "water_flow_m3_h": water_flow_m3_h,
        "supply_water_temperature_c": supply_water_temperature_c,
        "return_water_temperature_c": return_water_temperature_c,
        "water_side_cooling_kw": water_side_cooling_kw,
        "cooling_load_for_q_ac_kw": cooling_load_for_q_ac_kw,
        "cooling_power_w": cooling_power_w,
        "internal_load_w": current_internal_load_w,
        "solar_gain_w": current_solar_gain_w,
        "thermal_mass_load_w": current_thermal_mass_load_w,
        "schedule_time_s": schedule_time_s,
    }
    return inputs, diagnostics


def run_model_with_measurements(
    config: dict[str, Any],
) -> tuple[list[dict[str, float | str]], dict[str, float]]:
    """Run building RC model using measured weather and cooling load."""
    columns = config["columns"]
    options = config["model_inputs"]
    max_internal_step_s = float(options.get("max_internal_step_s", 60.0))
    multipliers = config.get("calibration_multipliers", {})
    building_config = load_json_config(project_path(config["building_input_path"]))
    raw_measurement_rows = load_measurement_rows(project_path(config["measurement_csv_path"]))
    raw_measurement_rows = maybe_add_solar_measurements(
        raw_measurement_rows,
        config,
        PROJECT_ROOT,
    )
    measurement_rows, skipped_missing_input_rows = _filter_complete_measurement_rows(
        raw_measurement_rows,
        config,
    )
    if len(measurement_rows) < 2:
        raise ValueError("measurement data must contain at least two rows")

    schedules = building_config.get("schedules", {})
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
    thermal_mass_heat_capacity_schedule = (
        make_daily_schedule(schedules["thermal_mass_heat_capacity_j_per_k"])
        if options["use_building_thermal_mass_heat_capacity_schedule"]
        and "thermal_mass_heat_capacity_j_per_k" in schedules
        else None
    )
    resolved_schedules = {
        "internal_load_schedule": internal_load_schedule,
        "thermal_mass_load_schedule": thermal_mass_load_schedule,
        "solar_gain_schedule": solar_gain_schedule,
        "thermal_mass_heat_capacity_schedule": thermal_mass_heat_capacity_schedule,
    }

    active_parameters = building_parameters_for_calibration_values(
        building_config,
        multipliers,
    )
    active_rc_parameters = _rc_parameter_dict(active_parameters)
    prior_messages = _building_type_prior_messages(config, active_rc_parameters)
    model = BuildingRCModel(active_parameters)
    first_measured_indoor = _to_float(
        measurement_rows[0],
        columns["measured_indoor_temperature_c"],
    )
    state = BuildingRCState(
        indoor_air_temperature_c=(
            first_measured_indoor
            if options["initialize_indoor_temperature_from_measured_column"]
            else building_config["initial_state"]["indoor_air_temperature_c"]
        ),
        thermal_mass_temperature_c=_initial_thermal_mass_temperature_c(
            config=config,
            first_measured_indoor=first_measured_indoor,
            first_clock_hour=_clock_time_s(measurement_rows[0], columns["time"]) / 3600.0,
            options=options,
            building_config=building_config,
        ),
    )

    output_rows: list[dict[str, float | str]] = []
    negative_cooling_count = 0
    for index, measurement in enumerate(measurement_rows):
        time_h = _to_float(measurement, columns["elapsed_h"])
        time_s = time_h * 3600.0
        inputs, input_diagnostics = _building_input_from_measurement(
            measurement,
            columns,
            options,
            building_config,
            resolved_schedules,
            multipliers,
        )
        schedule_time_s = input_diagnostics["schedule_time_s"]
        measured_cooling_kw = input_diagnostics["measured_cooling_kw"]
        water_flow_m3_h = input_diagnostics["water_flow_m3_h"]
        supply_water_temperature_c = input_diagnostics["supply_water_temperature_c"]
        return_water_temperature_c = input_diagnostics["return_water_temperature_c"]
        water_side_cooling_kw = input_diagnostics["water_side_cooling_kw"]
        cooling_power_w = input_diagnostics["cooling_power_w"]
        current_internal_load_w = input_diagnostics["internal_load_w"]
        current_solar_gain_w = input_diagnostics["solar_gain_w"]
        current_thermal_mass_load_w = input_diagnostics["thermal_mass_load_w"]
        cooling_load_for_q_ac_kw = input_diagnostics["cooling_load_for_q_ac_kw"]
        if cooling_load_for_q_ac_kw < 0:
            negative_cooling_count += 1
        measured_indoor_c = _to_float(measurement, columns["measured_indoor_temperature_c"])
        outdoor_c = _to_float(measurement, columns["outdoor_air_temperature_c"])
        sample = model.sample(time_s, state, inputs)
        error_c = sample.indoor_air_temperature_c - measured_indoor_c
        output_rows.append(
            {
                "time": measurement[columns["time"]],
                "elapsed_h": time_h,
                "clock_hour": schedule_time_s / 3600.0,
                "outdoor_air_temperature_c": outdoor_c,
                "measured_indoor_temperature_c": measured_indoor_c,
                "simulated_indoor_temperature_c": sample.indoor_air_temperature_c,
                "indoor_temperature_error_c": error_c,
                "measured_cooling_load_kw": measured_cooling_kw,
                "water_side_cooling_load_kw": water_side_cooling_kw,
                "water_flow_m3_h": water_flow_m3_h,
                "supply_water_temperature_c": supply_water_temperature_c,
                "return_water_temperature_c": return_water_temperature_c,
                "cooling_power_used_kw": cooling_power_w / 1000.0,
                "internal_load_used_kw": current_internal_load_w / 1000.0,
                "solar_irradiance_used_w_m2": (
                    float(measurement["measured_solar_irradiance_w_m2"])
                    if measurement.get("measured_solar_irradiance_w_m2", "").strip()
                    else 0.0
                ),
                "solar_gain_used_kw": current_solar_gain_w / 1000.0,
                "thermal_mass_load_used_kw": current_thermal_mass_load_w / 1000.0,
                "thermal_mass_temperature_c": sample.thermal_mass_temperature_c,
            }
        )

        if index < len(measurement_rows) - 1:
            next_time_h = _to_float(measurement_rows[index + 1], columns["elapsed_h"])
            dt_s = (next_time_h - time_h) * 3600.0
            state = _step_with_substeps(
                model,
                state,
                inputs,
                dt_s,
                max_internal_step_s,
            )

    errors = [float(row["indoor_temperature_error_c"]) for row in output_rows]
    measured_values = [
        float(row["measured_indoor_temperature_c"])
        for row in output_rows
    ]
    metrics = {
        "row_count": float(len(output_rows)),
        "skipped_missing_input_rows": float(skipped_missing_input_rows),
        "negative_cooling_load_rows": float(negative_cooling_count),
        "mae_c": _mean([abs(error) for error in errors]),
        "rmse_c": _rmse(errors),
        "bias_c": _mean(errors),
        "nmbe_percent": _nmbe_percent(errors, measured_values),
        "cv_rmse_percent": _cv_rmse_percent(errors, measured_values),
        "first_measured_indoor_temperature_c": first_measured_indoor,
        "initial_thermal_mass_temperature_c": state.thermal_mass_temperature_c,
        "final_simulated_indoor_temperature_c": float(output_rows[-1]["simulated_indoor_temperature_c"]),
        "final_measured_indoor_temperature_c": float(output_rows[-1]["measured_indoor_temperature_c"]),
        "active_rc_parameters": active_rc_parameters,
        "building_type_prior_messages": prior_messages,
    }
    return output_rows, metrics


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


def export_temperature_plots(
    rows: Sequence[dict[str, float | str]],
    paths: dict[str, Path],
    metrics: dict[str, float] | None = None,
) -> None:
    """Export separate measured and simulated temperature plots."""
    plot_x_values = _aligned_plot_x_values(rows)
    simulated_points = [
        ResultSeriesPoint(
            time_s=time_h * 3600.0,
            time_h=time_h,
            value_kw=float(row["simulated_indoor_temperature_c"]),
        )
        for row, time_h in zip(rows, plot_x_values)
    ]
    measured_points = [
        ResultSeriesPoint(
            time_s=time_h * 3600.0,
            time_h=time_h,
            value_kw=float(row["measured_indoor_temperature_c"]),
        )
        for row, time_h in zip(rows, plot_x_values)
    ]
    export_series_png(
        paths["simulated_png"],
        simulated_points,
        title="Simulated Indoor Temperature",
        y_label="T_sim (degC)",
    )
    export_series_png(
        paths["measured_png"],
        measured_points,
        title="Measured Indoor Temperature",
        y_label="T_meas (degC)",
    )
    export_temperature_comparison_png(rows, paths["comparison_png"], metrics=metrics)
    export_cooling_load_comparison_png(rows, paths["cooling_load_comparison_png"])
    export_indoor_heat_source_png(rows, paths["indoor_heat_source_png"])


def build_indoor_heat_source_rows(
    rows: Sequence[dict[str, float | str]],
) -> list[dict[str, float | str]]:
    """Build a compact table for indoor heat-source time series."""
    output_rows: list[dict[str, float | str]] = []
    for row in rows:
        internal_load_kw = float(row["internal_load_used_kw"])
        thermal_mass_load_kw = float(row["thermal_mass_load_used_kw"])
        solar_gain_kw = float(row["solar_gain_used_kw"])
        output_rows.append(
            {
                "time": row["time"],
                "elapsed_h": float(row["elapsed_h"]),
                "clock_hour": float(row["clock_hour"]),
                "internal_load_used_kw": internal_load_kw,
                "solar_gain_used_kw": solar_gain_kw,
                "thermal_mass_load_used_kw": thermal_mass_load_kw,
                "total_indoor_heat_source_kw": (
                    internal_load_kw + solar_gain_kw + thermal_mass_load_kw
                ),
            }
        )
    return output_rows


def export_indoor_heat_source_png(
    rows: Sequence[dict[str, float | str]],
    path: str | Path,
    width: int = 1100,
    height: int = 520,
) -> None:
    """Export indoor heat-source time series."""
    heat_rows = build_indoor_heat_source_rows(rows)
    if not heat_rows:
        raise ValueError("rows must not be empty")

    margin_left = 150
    margin_right = 36
    margin_top = 70
    margin_bottom = 92
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom

    x_values = _aligned_plot_x_values(heat_rows)
    internal_values = [float(row["internal_load_used_kw"]) for row in heat_rows]
    solar_values = [float(row["solar_gain_used_kw"]) for row in heat_rows]
    thermal_mass_values = [float(row["thermal_mass_load_used_kw"]) for row in heat_rows]
    total_values = [float(row["total_indoor_heat_source_kw"]) for row in heat_rows]
    y_values = internal_values + solar_values + thermal_mass_values + total_values
    x_min, x_max = _x_axis_bounds(x_values)
    y_min, y_max = _nice_y_bounds(y_values)

    def x_coord(value: float) -> float:
        return margin_left + (value - x_min) / (x_max - x_min) * plot_width

    def y_coord(value: float) -> float:
        return margin_top + (y_max - value) / (y_max - y_min) * plot_height

    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font = _plot_font()
    title_font = _plot_font(bold=True)
    axis_title_font = _plot_font(bold=True)
    axis_y = margin_top + plot_height
    plot_center_x = margin_left + plot_width / 2
    plot_center_y = margin_top + plot_height / 2
    draw.text((plot_center_x, margin_top - 18), "Indoor Heat Source Time Series", fill="#111111", font=title_font, anchor="mm")
    draw.line((margin_left, margin_top, margin_left, axis_y), fill="#222222", width=2)
    draw.line((margin_left, axis_y, width - margin_right, axis_y), fill="#222222", width=2)
    _draw_time_axis_ticks(draw, x_coord, axis_y, margin_top, x_min, x_max, font)
    _draw_y_axis_ticks(draw, y_coord, margin_left, width - margin_right, y_min, y_max, font)

    def series_points(values: Sequence[float]) -> list[tuple[float, float]]:
        return [
            (x_coord(time_h), y_coord(value))
            for time_h, value in zip(x_values, values)
        ]

    draw.line(series_points(internal_values), fill="#1f77b4", width=2)
    draw.line(series_points(solar_values), fill="#ff7f0e", width=2)
    draw.line(series_points(thermal_mass_values), fill="#2ca02c", width=3)
    draw.line(series_points(total_values), fill="#d62728", width=2)

    legend_x = margin_left + 12
    legend_y = margin_top + 22
    draw.line((legend_x, legend_y, legend_x + 28, legend_y), fill="#1f77b4", width=2)
    draw.text((legend_x + 36, legend_y), "Internal", fill="#111111", font=font, anchor="lm")
    draw.line((legend_x + 130, legend_y, legend_x + 158, legend_y), fill="#ff7f0e", width=2)
    draw.text((legend_x + 166, legend_y), "Solar", fill="#111111", font=font, anchor="lm")
    draw.line((legend_x + 248, legend_y, legend_x + 276, legend_y), fill="#2ca02c", width=3)
    draw.text((legend_x + 284, legend_y), "Thermal mass", fill="#111111", font=font, anchor="lm")
    draw.line((legend_x + 470, legend_y, legend_x + 498, legend_y), fill="#d62728", width=2)
    draw.text((legend_x + 506, legend_y), "Total", fill="#111111", font=font, anchor="lm")

    draw.text((plot_center_x, axis_y + 48), "Time (h)", fill="#111111", font=axis_title_font, anchor="mm")
    _draw_vertical_label(image, "Heat source (kW)", (54, plot_center_y), axis_title_font)

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="PNG")


def export_cooling_load_comparison_png(
    rows: Sequence[dict[str, float | str]],
    path: str | Path,
    width: int = 1100,
    height: int = 520,
) -> None:
    """Export measured cooling load and water-side calculated cooling load."""
    if not rows:
        raise ValueError("rows must not be empty")

    margin_left = 150
    margin_right = 36
    margin_top = 70
    margin_bottom = 92
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom

    x_values = _aligned_plot_x_values(rows)
    measured_values = [float(row["measured_cooling_load_kw"]) for row in rows]
    water_side_values = [float(row["water_side_cooling_load_kw"]) for row in rows]
    y_values = measured_values + water_side_values
    x_min, x_max = _x_axis_bounds(x_values)
    y_min, y_max = _nice_y_bounds(y_values)

    def x_coord(value: float) -> float:
        return margin_left + (value - x_min) / (x_max - x_min) * plot_width

    def y_coord(value: float) -> float:
        return margin_top + (y_max - value) / (y_max - y_min) * plot_height

    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font = _plot_font()
    title_font = _plot_font(bold=True)
    axis_title_font = _plot_font(bold=True)
    axis_y = margin_top + plot_height
    plot_center_x = margin_left + plot_width / 2
    plot_center_y = margin_top + plot_height / 2
    draw.text((plot_center_x, margin_top - 18), "CSV Cooling Load vs Water-Side Calculated Cooling Load", fill="#111111", font=title_font, anchor="mm")
    draw.line((margin_left, margin_top, margin_left, axis_y), fill="#222222", width=2)
    draw.line((margin_left, axis_y, width - margin_right, axis_y), fill="#222222", width=2)
    _draw_time_axis_ticks(draw, x_coord, axis_y, margin_top, x_min, x_max, font)
    _draw_y_axis_ticks(draw, y_coord, margin_left, width - margin_right, y_min, y_max, font)

    measured_points = [
        (x_coord(time_h), y_coord(value))
        for time_h, value in zip(x_values, measured_values)
    ]
    water_side_points = [
        (x_coord(time_h), y_coord(value))
        for time_h, value in zip(x_values, water_side_values)
    ]
    draw.line(measured_points, fill="#1f77b4", width=3)
    draw.line(water_side_points, fill="#ff7f0e", width=2)

    legend_x = margin_left + 12
    legend_y = margin_top + 22
    draw.line((legend_x, legend_y, legend_x + 28, legend_y), fill="#1f77b4", width=3)
    draw.text((legend_x + 36, legend_y), "CSV cooling_load_kw", fill="#111111", font=font, anchor="lm")
    draw.line((legend_x, legend_y + 32, legend_x + 28, legend_y + 32), fill="#ff7f0e", width=2)
    draw.text((legend_x + 36, legend_y + 32), "Flow * cp * dT", fill="#111111", font=font, anchor="lm")

    draw.text((plot_center_x, axis_y + 48), "Time (h)", fill="#111111", font=axis_title_font, anchor="mm")
    _draw_vertical_label(image, "Cooling load (kW)", (54, plot_center_y), axis_title_font)

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="PNG")


def export_temperature_comparison_png(
    rows: Sequence[dict[str, float | str]],
    path: str | Path,
    width: int = 1100,
    height: int = 520,
    metrics: dict[str, float] | None = None,
) -> None:
    """Export measured-vs-simulated indoor temperature comparison."""
    if not rows:
        raise ValueError("rows must not be empty")

    margin_left = 150
    margin_right = 36
    margin_top = 70
    margin_bottom = 92
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom

    x_values = _aligned_plot_x_values(rows)
    measured_values = [float(row["measured_indoor_temperature_c"]) for row in rows]
    simulated_values = [float(row["simulated_indoor_temperature_c"]) for row in rows]
    outdoor_values = [float(row["outdoor_air_temperature_c"]) for row in rows]
    y_values = measured_values + simulated_values + outdoor_values
    x_min, x_max = _x_axis_bounds(x_values)
    y_min, y_max = _nice_y_bounds(y_values)

    def x_coord(value: float) -> float:
        return margin_left + (value - x_min) / (x_max - x_min) * plot_width

    def y_coord(value: float) -> float:
        return margin_top + (y_max - value) / (y_max - y_min) * plot_height

    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font = _plot_font()
    title_font = _plot_font(bold=True)
    axis_title_font = _plot_font(bold=True)
    axis_y = margin_top + plot_height
    plot_center_x = margin_left + plot_width / 2
    plot_center_y = margin_top + plot_height / 2
    draw.text((plot_center_x, margin_top - 18), "Measured, Simulated, and Outdoor Temperature", fill="#111111", font=title_font, anchor="mm")
    draw.line((margin_left, margin_top, margin_left, axis_y), fill="#222222", width=2)
    draw.line((margin_left, axis_y, width - margin_right, axis_y), fill="#222222", width=2)
    _draw_time_axis_ticks(draw, x_coord, axis_y, margin_top, x_min, x_max, font)
    _draw_y_axis_ticks(draw, y_coord, margin_left, width - margin_right, y_min, y_max, font)

    measured_points = [
        (x_coord(time_h), y_coord(value))
        for time_h, value in zip(x_values, measured_values)
    ]
    simulated_points = [
        (x_coord(time_h), y_coord(value))
        for time_h, value in zip(x_values, simulated_values)
    ]
    outdoor_points = [
        (x_coord(time_h), y_coord(value))
        for time_h, value in zip(x_values, outdoor_values)
    ]
    draw.line(measured_points, fill="#1f77b4", width=3)
    draw.line(simulated_points, fill="#d62728", width=3)
    draw.line(outdoor_points, fill="#9467bd", width=2)

    legend_y = margin_top + 22
    legend_x = margin_left + 12
    legend_slot_w = 180
    legend_line_w = 28
    legend_text_gap = 8
    legend_items = (
        ("Measured", "#1f77b4", 3),
        ("Simulated", "#d62728", 3),
        ("Outdoor", "#9467bd", 2),
    )
    for index, (label, color, width_px) in enumerate(legend_items):
        item_x = legend_x + index * legend_slot_w
        draw.line(
            (item_x, legend_y, item_x + legend_line_w, legend_y),
            fill=color,
            width=width_px,
        )
        draw.text(
            (item_x + legend_line_w + legend_text_gap, legend_y),
            label,
            fill="#111111",
            font=font,
            anchor="lm",
        )
    if metrics is not None:
        metric_right_x = width - margin_right - 10
        metric_slot_w = 235
        metric_items = (
            (f"NMBE={metrics['nmbe_percent']:.3f}%", metric_right_x - metric_slot_w),
            (f"CV(RMSE)={metrics['cv_rmse_percent']:.3f}%", metric_right_x),
        )
        for label, right_x in metric_items:
            draw.text(
                (right_x, legend_y),
                label,
                fill="#111111",
                font=font,
                anchor="rm",
            )

    draw.text((plot_center_x, axis_y + 48), "Time (h)", fill="#111111", font=axis_title_font, anchor="mm")
    _draw_vertical_label(image, "Temperature (degC)", (54, plot_center_y), axis_title_font)

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="PNG")


def main() -> int:
    """Run the measured-data building RC simulation."""
    run_config_path = (
        project_path(sys.argv[1])
        if len(sys.argv) > 1
        else DEFAULT_RUN_CONFIG_PATH
    )
    config = load_run_config(run_config_path)
    paths = output_paths(config)
    rows, metrics = run_model_with_measurements(config)
    write_dict_rows(paths["comparison_csv"], rows)
    write_dict_rows(paths["indoor_heat_source_csv"], build_indoor_heat_source_rows(rows))
    paths["metrics_json"].parent.mkdir(parents=True, exist_ok=True)
    paths["metrics_json"].write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    export_temperature_plots(rows, paths, metrics=metrics)

    print(f"run config: {run_config_path}")
    print(f"measurement csv: {project_path(config['measurement_csv_path'])}")
    if config.get("solar_measurement"):
        print(
            "solar measurement csv: "
            f"{project_path(config['solar_measurement']['source_csv_path'])}"
        )
    print(f"building input: {project_path(config['building_input_path'])}")
    print(f"output csv: {paths['comparison_csv']}")
    print(f"indoor heat source csv: {paths['indoor_heat_source_csv']}")
    print(f"metrics json: {paths['metrics_json']}")
    print(f"simulated temperature figure: {paths['simulated_png']}")
    print(f"measured temperature figure: {paths['measured_png']}")
    print(f"comparison figure: {paths['comparison_png']}")
    print(f"cooling load comparison figure: {paths['cooling_load_comparison_png']}")
    print(f"indoor heat source figure: {paths['indoor_heat_source_png']}")
    print("used measured columns from config:")
    for logical_name, column_name in config["columns"].items():
        if logical_name in (
            "time",
            "elapsed_h",
            "outdoor_air_temperature_c",
            "measured_indoor_temperature_c",
            "measured_cooling_load_kw",
            "water_flow_m3_h",
            "supply_water_temperature_c",
            "return_water_temperature_c",
            "measured_internal_load_kw",
            "measured_solar_gain_kw",
        ):
            print(f"  {logical_name}: {column_name}")
    if config["model_inputs"]["use_measured_internal_load_as_internal_load"]:
        print(
            "internal_load_w source: measured CSV column "
            f"{config['columns']['measured_internal_load_kw']}"
        )
    if config["model_inputs"].get("use_measured_water_side_q_ac"):
        print(
            "Q_ac source: measured water flow and supply/return temperatures "
            f"({config['columns']['water_flow_m3_h']}, "
            f"{config['columns']['supply_water_temperature_c']}, "
            f"{config['columns']['return_water_temperature_c']})"
        )
    elif config["model_inputs"]["use_measured_cooling_load_as_q_ac"]:
        print(
            "Q_ac source: measured CSV column "
            f"{config['columns']['measured_cooling_load_kw']}"
        )
    if config["model_inputs"]["use_measured_solar_gain"]:
        print(
            "solar_gain_w source: measured CSV column "
            f"{config['columns']['measured_solar_gain_kw']}"
        )
    elif config["model_inputs"]["use_building_solar_gain_schedule"]:
        print("solar_gain_w source: assumed schedule in building input file")
    print("used model schedules from config:")
    for option_name, schedule_name in (
        ("use_building_internal_load_schedule", "internal_load_w"),
        ("use_building_solar_gain_schedule", "solar_gain_w"),
        ("use_building_thermal_mass_load_schedule", "thermal_mass_load_w"),
        (
            "use_building_thermal_mass_heat_capacity_schedule",
            "thermal_mass_heat_capacity_j_per_k",
        ),
    ):
        if config["model_inputs"][option_name]:
            print(f"  {schedule_name}")
    print(f"rows: {metrics['row_count']:.0f}")
    print(f"skipped rows with missing required inputs: {metrics['skipped_missing_input_rows']:.0f}")
    print(f"negative cooling load rows clamped to 0: {metrics['negative_cooling_load_rows']:.0f}")
    print(f"MAE: {metrics['mae_c']:.3f} degC")
    print(f"RMSE: {metrics['rmse_c']:.3f} degC")
    print(f"Bias: {metrics['bias_c']:.3f} degC")
    print(f"NMBE: {metrics['nmbe_percent']:.3f} %")
    print(f"CV(RMSE): {metrics['cv_rmse_percent']:.3f} %")
    if metrics.get("building_type_prior_messages"):
        print("building type prior check:")
        for message in metrics["building_type_prior_messages"]:
            print(f"  {message}")
    print(
        "final indoor temperature: "
        f"sim={metrics['final_simulated_indoor_temperature_c']:.3f} degC, "
        f"measured={metrics['final_measured_indoor_temperature_c']:.3f} degC"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
