"""Rebuild measurement-run PNG figures from the existing result CSV only."""

from __future__ import annotations

import json

from run_building_with_measurements import (
    export_temperature_plots,
    load_measurement_rows,
    load_run_config,
    output_paths,
)


def main() -> int:
    """Regenerate figures without rerunning the building RC model."""
    config = load_run_config()
    paths = output_paths(config)
    comparison_csv = paths["comparison_csv"]
    if not comparison_csv.exists():
        raise FileNotFoundError(
            "Existing result CSV was not found. Run "
            "examples/run_building_with_measurements.py once before replotting."
        )

    rows = load_measurement_rows(comparison_csv)
    metrics = json.loads(paths["metrics_json"].read_text(encoding="utf-8"))
    export_temperature_plots(rows, paths, metrics=metrics)

    print(f"read existing result csv: {comparison_csv}")
    print(f"read existing metrics json: {paths['metrics_json']}")
    print(f"updated simulated temperature figure: {paths['simulated_png']}")
    print(f"updated measured temperature figure: {paths['measured_png']}")
    print(f"updated comparison figure: {paths['comparison_png']}")
    print(f"updated cooling load comparison figure: {paths['cooling_load_comparison_png']}")
    print(f"updated indoor heat source figure: {paths['indoor_heat_source_png']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
