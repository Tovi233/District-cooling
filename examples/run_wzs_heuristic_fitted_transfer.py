"""Fit RC parameters on WZS, then transfer them to WZS1 and WZS2."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))
sys.path.insert(0, str(PROJECT_ROOT))

from district_cooling.calibration import calibrate_building_rc, write_calibration_outputs  # noqa: E402
from district_cooling.io import load_json_config, write_dict_rows  # noqa: E402
from examples.run_building_with_measurements import (  # noqa: E402
    build_indoor_heat_source_rows,
    export_temperature_plots,
    output_paths,
    run_model_with_measurements,
)


CALIBRATION_CONFIG_PATH = (
    "src/district_cooling/load/inputs/calibration/"
    "building_rc_structured_physical_calibration_config.json"
)
RUN_CONFIGS = (
    (
        "WZS",
        "src/district_cooling/load/inputs/measurements/wzs_building_run_config.json",
        "wzs_with_wzs_fitted_rc",
    ),
    (
        "WZS1",
        "src/district_cooling/load/inputs/measurements/wzs1_building_validation_run_config.json",
        "wzs1_with_wzs_fitted_rc",
    ),
    (
        "WZS2",
        "src/district_cooling/load/inputs/measurements/wzs2_building_validation_run_config.json",
        "wzs2_with_wzs_fitted_rc",
    ),
)
OUTPUT_ROOT = PROJECT_ROOT / "run_cache" / "wzs_heuristic_initial_fitted_transfer"


def project_path(relative_path: str) -> Path:
    return PROJECT_ROOT / relative_path


def main() -> int:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    calibration_config = load_json_config(project_path(CALIBRATION_CONFIG_PATH))
    calibration_config = dict(calibration_config)
    calibration_config["output_dir"] = (
        "run_cache/wzs_heuristic_initial_fitted_transfer/calibration"
    )
    result, train_rows, validation_rows = calibrate_building_rc(
        PROJECT_ROOT,
        calibration_config,
    )
    calibration_paths = write_calibration_outputs(
        PROJECT_ROOT,
        calibration_config,
        result,
        train_rows,
        validation_rows,
    )

    summary_rows: list[dict[str, float | str]] = []
    comparison_images: list[tuple[str, Path]] = []
    for label, config_path, output_name in RUN_CONFIGS:
        run_config = load_json_config(project_path(config_path))
        run_config = dict(run_config)
        run_config["calibration_multipliers"] = result.best_parameters
        run_config["output_dir"] = (
            f"run_cache/wzs_heuristic_initial_fitted_transfer/{output_name}"
        )
        run_output_dir = project_path(run_config["output_dir"])
        run_output_dir.mkdir(parents=True, exist_ok=True)
        (run_output_dir / "run_config_used.json").write_text(
            json.dumps(run_config, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        rows, metrics = run_model_with_measurements(run_config)
        paths = output_paths(run_config)
        write_dict_rows(paths["comparison_csv"], rows)
        write_dict_rows(
            paths["indoor_heat_source_csv"],
            build_indoor_heat_source_rows(rows),
        )
        paths["metrics_json"].write_text(
            json.dumps(metrics, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        export_temperature_plots(rows, paths, metrics=metrics)
        comparison_images.append((label, paths["comparison_png"]))
        summary_rows.append(
            {
                "dataset": label,
                "row_count": metrics["row_count"],
                "skipped_missing_input_rows": metrics["skipped_missing_input_rows"],
                "mae_c": metrics["mae_c"],
                "rmse_c": metrics["rmse_c"],
                "bias_c": metrics["bias_c"],
                "nmbe_percent": metrics["nmbe_percent"],
                "cv_rmse_percent": metrics["cv_rmse_percent"],
                "initial_thermal_mass_temperature_c": metrics[
                    "initial_thermal_mass_temperature_c"
                ],
            }
        )

    summary_csv = OUTPUT_ROOT / "three_dataset_metrics_summary.csv"
    write_dict_rows(summary_csv, summary_rows)
    fitted_params_json = OUTPUT_ROOT / "wzs_fitted_rc_parameters.json"
    fitted_params_json.write_text(
        json.dumps(
            {
                "best_parameters": result.best_parameters,
                "derived_rc_parameters": result.derived_rc_parameters,
                "calibration_result": asdict(result),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    vertical_png = OUTPUT_ROOT / "three_dataset_temperature_comparison_vertical.png"
    _stack_images_vertically(comparison_images, vertical_png)

    print(f"calibration result: {calibration_paths['result_json']}")
    print(f"fitted RC parameters: {fitted_params_json}")
    print(f"metrics summary: {summary_csv}")
    print(f"vertical comparison figure: {vertical_png}")
    print("derived RC parameters:")
    for name, value in result.derived_rc_parameters.items():
        print(f"  {name}: {value:.6g}")
    print("three-dataset metrics:")
    for row in summary_rows:
        print(
            f"  {row['dataset']}: RMSE={row['rmse_c']:.3f} degC, "
            f"CV(RMSE)={row['cv_rmse_percent']:.3f}%, "
            f"T_m0={row['initial_thermal_mass_temperature_c']:.3f} degC"
        )
    return 0


def _stack_images_vertically(
    image_paths: list[tuple[str, Path]],
    output_path: Path,
) -> None:
    images = [(label, Image.open(path).convert("RGB")) for label, path in image_paths]
    if not images:
        raise ValueError("image_paths must not be empty")
    width = max(image.width for _, image in images)
    gap = 18
    label_height = 42
    total_height = (
        sum(image.height + label_height for _, image in images)
        + gap * (len(images) - 1)
    )
    canvas = Image.new("RGB", (width, total_height), "white")
    draw = ImageDraw.Draw(canvas)
    font = _font(26, bold=True)
    y = 0
    for label, image in images:
        draw.text((24, y + label_height / 2), label, fill="#111111", font=font, anchor="lm")
        y += label_height
        x = (width - image.width) // 2
        canvas.paste(image, (x, y))
        y += image.height + gap
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, format="PNG")
    for _, image in images:
        image.close()


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    names = (
        ("arialbd.ttf", "DejaVuSans-Bold.ttf", "arial.ttf", "DejaVuSans.ttf")
        if bold
        else ("arial.ttf", "DejaVuSans.ttf")
    )
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


if __name__ == "__main__":
    raise SystemExit(main())
