"""High-level building RC parameter calibration workflow."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
from typing import Any

from district_cooling.io import load_json_config, write_dict_rows
from district_cooling.load import building_parameters_from_config
from district_cooling.load.solar_measurements import maybe_add_solar_measurements

from .objective import (
    building_parameters_for_calibration_values,
    detect_temperature_period,
    duration_h,
    filter_complete_rows,
    load_measurement_rows,
    metrics_from_rows,
    project_path,
    regularized_loss,
    simulate_rows,
    split_rows_covering_min_duration,
    structured_parameters,
)
from .optimizer import (
    coordinate_search,
    random_log_search,
    scipy_differential_evolution_l_bfgs_b,
)
from .parameter_space import parameters_for_level, parameters_from_config, recommended_level


@dataclass(frozen=True)
class BuildingCalibrationResult:
    """Full result from one building RC calibration run."""

    dataset_name: str
    mode: str
    calibration_level: int
    selected_parameters: list[str]
    reference_parameters: dict[str, float]
    best_parameters: dict[str, float]
    derived_rc_parameters: dict[str, float]
    best_multipliers: dict[str, float]
    train_metrics: dict[str, float]
    validation_metrics: dict[str, float]
    baseline_train_metrics: dict[str, float]
    baseline_validation_metrics: dict[str, float]
    regularized_train_loss: float
    evaluations: int
    hit_bounds: list[str]
    skipped_missing_input_rows: int
    usable_duration_h: float
    warning_messages: list[str]


def _metrics_dict(metrics: Any) -> dict[str, float]:
    return {
        key: float(value)
        for key, value in asdict(metrics).items()
    }


def _rc_parameter_dict(parameters: Any) -> dict[str, float]:
    """Return final RC parameters as a plain JSON-serializable dict."""
    return {
        "R_outwall": float(parameters.outwall_thermal_resistance_k_per_w),
        "R_m": float(parameters.mass_thermal_resistance_k_per_w),
        "C_indoor": float(parameters.indoor_air_heat_capacity_j_per_k),
        "C_m": float(parameters.thermal_mass_heat_capacity_j_per_k),
    }


def _load_building_type_prior(
    root: Path,
    calibration_config: dict[str, Any],
) -> tuple[str, dict[str, Any]] | None:
    """Load an optional building-type RC prior from configuration."""
    prior_config = calibration_config.get("building_type_prior")
    if not prior_config:
        return None
    prior_path = project_path(root, prior_config["path"])
    prior_library = load_json_config(prior_path)
    category_key = str(prior_config["category"])
    category = prior_library["categories"][category_key]
    return category_key, category


def _prior_rc_ranges(category: dict[str, Any]) -> dict[str, dict[str, float]]:
    """Map source 2R2C prior ranges to this project's RC parameter names."""
    source = category["source"]
    return {
        "R_outwall": {
            "min": 1.0 / float(source["U_z"]["max"]),
            "max": 1.0 / float(source["U_z"]["min"]),
            "mean": 1.0 / float(source["U_z"]["mean"]),
        },
        "R_m": {
            "min": 1.0 / float(source["U_1"]["max"]),
            "max": 1.0 / float(source["U_1"]["min"]),
            "mean": 1.0 / float(source["U_1"]["mean"]),
        },
        "C_m": {
            "min": float(source["C_1"]["min"]),
            "max": float(source["C_1"]["max"]),
            "mean": float(source["C_1"]["mean"]),
        },
        "C_indoor": {
            "min": float(source["Cin"]["min"]),
            "max": float(source["Cin"]["max"]),
            "mean": float(source["Cin"]["mean"]),
        },
    }


def _prior_warning_messages(
    category_key: str,
    category: dict[str, Any],
    values: dict[str, float],
) -> list[str]:
    """Return warnings when fitted values are outside building-type prior ranges."""
    warnings = [f"Building type RC prior loaded: {category_key}."]
    ranges = _prior_rc_ranges(category)
    outside: list[str] = []
    for name, range_values in ranges.items():
        if name not in values:
            continue
        value = float(values[name])
        if value < range_values["min"] or value > range_values["max"]:
            outside.append(
                f"{name}={value:.6g} outside "
                f"[{range_values['min']:.6g}, {range_values['max']:.6g}]"
            )
    if outside:
        warnings.append(
            "Fitted parameters outside the building-type prior range: "
            + "; ".join(outside)
            + ". This may be acceptable when building scale differs from the prior dataset."
        )
    return warnings


def _rc_prior_constraint_loss(
    building_config: dict[str, Any],
    calibration_values: dict[str, float],
    prior_category: dict[str, Any] | None,
    parameter_names: list[str],
) -> float:
    """Return log-distance penalty for final RC values outside prior ranges."""
    if prior_category is None or not parameter_names:
        return 0.0
    ranges = _prior_rc_ranges(prior_category)
    parameters = building_parameters_for_calibration_values(
        building_config,
        calibration_values,
    )
    rc_values = _rc_parameter_dict(parameters)
    squared_distance = 0.0
    for name in parameter_names:
        value = rc_values[name]
        lower = ranges[name]["min"]
        upper = ranges[name]["max"]
        if value < lower:
            squared_distance += math.log(lower / value) ** 2
        elif value > upper:
            squared_distance += math.log(value / upper) ** 2
    return squared_distance ** 0.5


def _rc_prior_mean_loss(
    building_config: dict[str, Any],
    calibration_values: dict[str, float],
    prior_category: dict[str, Any] | None,
    parameter_names: list[str],
) -> float:
    """Return log-distance penalty from selected final RC values to prior means."""
    if prior_category is None or not parameter_names:
        return 0.0
    ranges = _prior_rc_ranges(prior_category)
    parameters = building_parameters_for_calibration_values(
        building_config,
        calibration_values,
    )
    rc_values = _rc_parameter_dict(parameters)
    return (
        sum(
            math.log(rc_values[name] / ranges[name]["mean"]) ** 2
            for name in parameter_names
        )
        / len(parameter_names)
    ) ** 0.5


def calibrate_building_rc(
    project_root: str | Path,
    calibration_config: dict[str, Any],
) -> tuple[BuildingCalibrationResult, list[dict[str, float | str]], list[dict[str, float | str]]]:
    """Run conservative parameter identification for a building RC model."""
    root = Path(project_root)
    run_config = load_json_config(
        project_path(root, calibration_config["measurement_run_config_path"])
    )
    building_config = load_json_config(project_path(root, run_config["building_input_path"]))
    building_type_prior = _load_building_type_prior(root, calibration_config)
    raw_rows = load_measurement_rows(project_path(root, run_config["measurement_csv_path"]))
    raw_rows = maybe_add_solar_measurements(raw_rows, run_config, root)
    rows, skipped_missing = filter_complete_rows(raw_rows, run_config)
    if len(rows) < 4:
        raise ValueError("at least four complete rows are required for calibration")

    usable_duration = duration_h(rows, run_config["columns"]["elapsed_h"])
    options = calibration_config.get("options", {})
    mode = str(calibration_config.get("mode", "multiplier"))
    base_parameters = building_parameters_from_config(building_config)
    physical_reference = {
        "R_outwall": base_parameters.outwall_thermal_resistance_k_per_w,
        "R_m": base_parameters.mass_thermal_resistance_k_per_w,
        "C_indoor": base_parameters.indoor_air_heat_capacity_j_per_k,
        "C_m": base_parameters.thermal_mass_heat_capacity_j_per_k,
    }
    if mode == "absolute":
        level = 0
        parameters = parameters_from_config(calibration_config["physical_parameters"])
        reference_values = {
            parameter.name: physical_reference.get(parameter.name, parameter.initial)
            for parameter in parameters
        }
    elif mode == "structured":
        level = int(options.get("force_level", 2))
        parameters = parameters_from_config(calibration_config["structured_parameters"])
        reference_values = {
            parameter.name: parameter.initial
            for parameter in parameters
        }
    elif mode in ("structured_prior", "structured_prior_dynamic"):
        level = int(options.get("force_level", 2))
        parameters = parameters_from_config(calibration_config["fitted_rc_parameters"])
        reference_rc_parameters = structured_parameters(
            building_config,
            calibration_config["reference_physical_parameters"],
        )
        structured_reference = _rc_parameter_dict(reference_rc_parameters)
        reference_values = {
            parameter.name: structured_reference.get(parameter.name, parameter.initial)
            for parameter in parameters
        }
    else:
        level = int(
            options.get(
                "force_level",
                recommended_level(
                    usable_duration,
                    requested_max_level=int(options.get("max_level", 3)),
                ),
            )
        )
        parameters = parameters_for_level(
            level,
            overrides=calibration_config.get("parameters", {}),
        )
        reference_values = {parameter.name: 1.0 for parameter in parameters}
    elapsed_column = run_config["columns"]["elapsed_h"]
    period_detection = detect_temperature_period(
        rows,
        elapsed_column=elapsed_column,
        temperature_column=run_config["columns"]["measured_indoor_temperature_c"],
        default_period_h=float(options.get("default_cycle_h", 24.0)),
        min_period_h=float(options.get("minimum_detectable_cycle_h", 6.0)),
        max_period_h=float(options.get("maximum_detectable_cycle_h", 48.0)),
    )
    detected_cycles = period_detection.cycle_count
    min_recommended_duration_h = float(
        options.get("minimum_recommended_duration_h", 48.0)
    )
    min_train_cycle_h = float(
        options.get("minimum_train_cycle_h", period_detection.period_h)
    )
    required_train_duration_h = (
        min_train_cycle_h
        if detected_cycles >= 1.0
        else 0.0
    )
    train_rows, validation_rows = split_rows_covering_min_duration(
        rows,
        train_fraction=float(options.get("train_fraction", 0.7)),
        elapsed_column=elapsed_column,
        min_train_duration_h=required_train_duration_h,
    )
    regularization_weight = float(options.get("regularization_weight", 0.08))
    dynamic_options = options.get("dynamic_loss")
    prior_constraint_weight = float(options.get("rc_prior_constraint_weight", 0.0))
    prior_constraint_parameters = [
        str(name)
        for name in options.get(
            "rc_prior_constraint_parameters",
            ["R_outwall", "R_m", "C_indoor", "C_m"],
        )
    ]
    prior_mean_weight = float(options.get("rc_prior_mean_weight", 0.0))
    prior_mean_parameters = [
        str(name)
        for name in options.get("rc_prior_mean_parameters", [])
    ]
    prior_constraint_category = building_type_prior[1] if building_type_prior else None

    baseline_train = simulate_rows(train_rows, run_config, building_config, {})
    baseline_validation = simulate_rows(validation_rows, run_config, building_config, {})

    def objective(values: dict[str, float]) -> float:
        output_rows = simulate_rows(train_rows, run_config, building_config, values)
        loss = regularized_loss(
            output_rows,
            values,
            regularization_weight,
            reference_values=reference_values,
            dynamic_options=dynamic_options,
        )
        if prior_constraint_weight > 0.0:
            loss += prior_constraint_weight * _rc_prior_constraint_loss(
                building_config,
                values,
                prior_constraint_category,
                prior_constraint_parameters,
            )
        if prior_mean_weight > 0.0:
            loss += prior_mean_weight * _rc_prior_mean_loss(
                building_config,
                values,
                prior_constraint_category,
                prior_mean_parameters,
            )
        return loss

    optimizer_name = str(options.get("optimizer", "scipy_de_l_bfgs_b"))
    if optimizer_name == "scipy_de_l_bfgs_b":
        optimization = scipy_differential_evolution_l_bfgs_b(
            parameters,
            objective,
            max_iterations=int(options.get("max_iterations", 40)),
            population_size=int(options.get("population_size", 10)),
            seed=int(options.get("random_seed", 42)),
            polish=bool(options.get("polish", True)),
        )
    else:
        random_samples = int(options.get("random_samples", 0))
        if random_samples > 0:
            random_result = random_log_search(
                parameters,
                objective,
                samples=random_samples,
                seed=int(options.get("random_seed", 42)),
            )
            initial_values = random_result.best_values
            initial_evaluations = random_result.evaluations
        else:
            initial_values = None
            initial_evaluations = 0
        optimization = coordinate_search(
            parameters,
            objective,
            max_iterations=int(options.get("max_iterations", 8)),
            initial_log_step=float(options.get("initial_log_step", 0.35)),
            initial_values=initial_values,
        )
        optimization = type(optimization)(
            best_values=optimization.best_values,
            best_loss=optimization.best_loss,
            evaluations=initial_evaluations + optimization.evaluations,
            hit_bounds=optimization.hit_bounds,
        )
    calibrated_train = simulate_rows(
        train_rows,
        run_config,
        building_config,
        optimization.best_values,
    )
    calibrated_validation = simulate_rows(
        validation_rows,
        run_config,
        building_config,
        optimization.best_values,
    )

    warnings: list[str] = []
    if building_type_prior is not None:
        warnings.extend(
            _prior_warning_messages(
                building_type_prior[0],
                building_type_prior[1],
                optimization.best_values,
            )
        )
    train_duration = duration_h(train_rows, elapsed_column)
    validation_duration = duration_h(validation_rows, elapsed_column)
    if usable_duration < min_recommended_duration_h or detected_cycles < 2.0:
        warnings.append(
            "Measured data are limited; using fixed parameters is recommended before fitting RC parameters."
        )
    if period_detection.confidence < float(options.get("minimum_cycle_confidence", 0.25)):
        warnings.append(
            "Dominant cycle detection has low confidence; fixed parameters or more measured data are recommended."
        )
    if required_train_duration_h > 0.0 and train_duration < required_train_duration_h:
        warnings.append(
            "Training data do not cover a full detected cycle; fitted parameters may be incomplete."
        )
    elif required_train_duration_h > 0.0:
        warnings.append(
            "Training split covers at least one detected cycle "
            f"({period_detection.period_h:.2f} h cycle, "
            f"{train_duration:.2f} h train, {validation_duration:.2f} h validation, "
            f"method={period_detection.method}, confidence={period_detection.confidence:.2f})."
        )
    if optimization.hit_bounds:
        warnings.append(
            "Some parameters reached their bounds; physical interpretation should be checked."
        )
    baseline_validation_metrics = metrics_from_rows(baseline_validation)
    validation_metrics = metrics_from_rows(calibrated_validation)
    if validation_metrics.rmse_c > baseline_validation_metrics.rmse_c:
        warnings.append(
            "Validation RMSE is worse than the baseline; this calibration may be overfitting."
        )

    result = BuildingCalibrationResult(
        dataset_name=str(calibration_config["dataset_name"]),
        mode=mode,
        calibration_level=level,
        selected_parameters=[parameter.name for parameter in parameters],
        reference_parameters=reference_values,
        best_parameters=optimization.best_values,
        derived_rc_parameters=_rc_parameter_dict(
            building_parameters_for_calibration_values(
                building_config,
                optimization.best_values,
            )
        ),
        best_multipliers=optimization.best_values if mode == "multiplier" else {},
        train_metrics=_metrics_dict(metrics_from_rows(calibrated_train)),
        validation_metrics=_metrics_dict(validation_metrics),
        baseline_train_metrics=_metrics_dict(metrics_from_rows(baseline_train)),
        baseline_validation_metrics=_metrics_dict(baseline_validation_metrics),
        regularized_train_loss=optimization.best_loss,
        evaluations=optimization.evaluations,
        hit_bounds=optimization.hit_bounds,
        skipped_missing_input_rows=skipped_missing,
        usable_duration_h=usable_duration,
        warning_messages=warnings,
    )
    return result, calibrated_train, calibrated_validation


def write_calibration_outputs(
    project_root: str | Path,
    calibration_config: dict[str, Any],
    result: BuildingCalibrationResult,
    train_rows: list[dict[str, float | str]],
    validation_rows: list[dict[str, float | str]],
) -> dict[str, Path]:
    """Write result JSON and train/validation time series CSV files."""
    output_dir = project_path(project_root, calibration_config["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    result_path = output_dir / "building_calibration_result.json"
    train_path = output_dir / "calibrated_train_timeseries.csv"
    validation_path = output_dir / "calibrated_validation_timeseries.csv"
    result_path.write_text(
        json.dumps(asdict(result), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_dict_rows(train_path, train_rows)
    write_dict_rows(validation_path, validation_rows)
    return {
        "result_json": result_path,
        "train_csv": train_path,
        "validation_csv": validation_path,
    }
