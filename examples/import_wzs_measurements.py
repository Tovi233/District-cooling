"""Import WZS measured data into the building load input folder."""

from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from district_cooling.load.measurement_import import import_wzs_measurements  # noqa: E402


DEFAULT_IMPORT_CONFIG_PATH = (
    SRC_DIR
    / "district_cooling"
    / "load"
    / "inputs"
    / "measurements"
    / "wzs_import_config.json"
)


def project_path(relative_path: str) -> Path:
    """Resolve a project-relative path from the import configuration."""
    return PROJECT_ROOT / relative_path


def main() -> int:
    """Import the WZS Excel workbook into normalized project inputs."""
    import_config_path = (
        project_path(sys.argv[1])
        if len(sys.argv) > 1
        else DEFAULT_IMPORT_CONFIG_PATH
    )
    import_config = json.loads(import_config_path.read_text(encoding="utf-8"))
    source_excel_path = project_path(import_config["source_excel_path"])
    output_csv_path = project_path(import_config["output_csv_path"])
    output_metadata_path = project_path(import_config["output_metadata_path"])

    summary = import_wzs_measurements(source_excel_path, output_csv_path)
    config = {
        "dataset_name": import_config.get("dataset_name", "wzs_building_calibration"),
        "source_excel_path": import_config["source_excel_path"],
        "normalized_csv_path": import_config["output_csv_path"],
        "time_column": "time",
        "elapsed_time_column_h": "elapsed_h",
        "time_step_s": summary.time_step_s,
        "row_count": summary.row_count,
        "start_time": summary.start_time.isoformat(sep=" "),
        "end_time": summary.end_time.isoformat(sep=" "),
        "recommended_building_calibration_columns": {
            "outdoor_air_temperature_c": "outdoor_air_temperature_c",
            "measured_indoor_temperature_c": "indoor_average_temperature_c",
            "measured_cooling_power_kw": "cooling_load_kw",
            "water_flow_m3_h": "water_flow_m3_h",
            "supply_water_temperature_c": "supply_water_temperature_c",
            "return_water_temperature_c": "return_water_temperature_c"
        },
        "notes": [
            "Use cooling_load_kw as measured Q_ac for the first building RC calibration.",
            "Rows with very small flow or negative cooling_load_kw should be flagged before parameter fitting.",
            "Humidity columns are preserved for future latent-load or comfort analysis."
        ]
    }
    output_metadata_path.parent.mkdir(parents=True, exist_ok=True)
    output_metadata_path.write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"imported rows: {summary.row_count}")
    print(f"time range: {summary.start_time} -> {summary.end_time}")
    print(f"time step: {summary.time_step_s:.0f} s")
    print(f"import config: {import_config_path}")
    print(f"source excel: {source_excel_path}")
    print(f"csv: {output_csv_path}")
    print(f"config: {output_metadata_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
