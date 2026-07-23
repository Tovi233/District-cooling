"""Identify conservative building RC multipliers from measured data."""

from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from district_cooling.calibration import (  # noqa: E402
    calibrate_building_rc,
    write_calibration_outputs,
)
from district_cooling.io import load_json_config  # noqa: E402


DEFAULT_CONFIG_PATH = (
    SRC_DIR
    / "district_cooling"
    / "load"
    / "inputs"
    / "calibration"
    / "building_rc_calibration_config.json"
)


def project_path(relative_path: str) -> Path:
    """Resolve a project-relative path."""
    return PROJECT_ROOT / relative_path


def main() -> int:
    """Run one building RC parameter-identification job."""
    config_path = project_path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CONFIG_PATH
    config = load_json_config(config_path)
    result, train_rows, validation_rows = calibrate_building_rc(PROJECT_ROOT, config)
    paths = write_calibration_outputs(
        PROJECT_ROOT,
        config,
        result,
        train_rows,
        validation_rows,
    )

    print(f"calibration config: {config_path}")
    print(f"result json: {paths['result_json']}")
    print(f"train csv: {paths['train_csv']}")
    print(f"validation csv: {paths['validation_csv']}")
    print(f"dataset: {result.dataset_name}")
    print(f"mode: {result.mode}")
    print(f"usable duration: {result.usable_duration_h:.2f} h")
    print(f"calibration level: {result.calibration_level}")
    print(f"selected parameters: {', '.join(result.selected_parameters)}")
    if result.mode in ("absolute", "structured", "structured_prior", "structured_prior_dynamic"):
        print("best fitted parameters:")
        for name, value in result.best_parameters.items():
            reference = result.reference_parameters[name]
            change_percent = (value / reference - 1.0) * 100.0
            print(
                f"  {name}: {value:.6g} "
                f"(reference={reference:.6g}, change={change_percent:+.2f}%)"
            )
        print("derived RC parameters:")
        for name, value in result.derived_rc_parameters.items():
            print(f"  {name}: {value:.6g}")
    else:
        print("best multipliers:")
        for name, value in result.best_multipliers.items():
            print(f"  {name}: {value:.6g}")
    print(
        "baseline validation: "
        f"RMSE={result.baseline_validation_metrics['rmse_c']:.3f} degC, "
        f"CV(RMSE)={result.baseline_validation_metrics['cv_rmse_percent']:.3f}%"
    )
    print(
        "calibrated validation: "
        f"RMSE={result.validation_metrics['rmse_c']:.3f} degC, "
        f"CV(RMSE)={result.validation_metrics['cv_rmse_percent']:.3f}%"
    )
    if result.hit_bounds:
        print(f"parameters at bounds: {', '.join(result.hit_bounds)}")
    if result.warning_messages:
        print("warnings:")
        for warning in result.warning_messages:
            print(f"  {warning}")
    print(json.dumps(result.best_parameters, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
