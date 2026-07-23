"""Main entry point for the connected district-cooling RC system."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

PLANT_INPUT_PATH = SRC_DIR / "district_cooling" / "plant" / "inputs" / "plant_basic.json"
NETWORK_INPUT_PATH = (
    SRC_DIR / "district_cooling" / "network" / "inputs" / "pipe_network_basic.json"
)
LOAD_INPUT_PATH = SRC_DIR / "district_cooling" / "load" / "inputs" / "building_basic.json"

from district_cooling.core import make_daily_schedule  # noqa: E402
from district_cooling.io import load_json_config, write_dict_rows  # noqa: E402
from district_cooling.load import (  # noqa: E402
    BuildingRCModel,
    BuildingRCState,
    building_parameters_from_config,
)
from district_cooling.network import (  # noqa: E402
    PipePairState,
    PipeRCParameters,
    PipeRCState,
    SupplyReturnPipeNetwork,
)
from district_cooling.plant import BasicPlantModel  # noqa: E402
from district_cooling.results import (  # noqa: E402
    export_input_data_summary_png,
    export_standard_results,
    prepare_run_cache,
)
from district_cooling.system import simulate_coupled_system  # noqa: E402


def build_plant_model() -> BasicPlantModel:
    """Build the central plant model from configuration."""
    plant_config = load_json_config(PLANT_INPUT_PATH)
    return BasicPlantModel.from_config(plant_config)


def print_plant_summary(plant_model: BasicPlantModel) -> None:
    """Print current plant temperatures and mode summaries."""
    plant_output = plant_model.output()
    print("Central plant parameter model ready.")
    print(f"Supply water temperature: {plant_output.supply_water_temperature_c:.3f} degC")
    if plant_output.return_water_temperature_c is None:
        print("Return water temperature: calculated by building and return pipe")
    else:
        print(f"Return water temperature: {plant_output.return_water_temperature_c:.3f} degC")

    for mode_name in ("air_conditioning", "ice_storage", "nominal"):
        try:
            summary = plant_model.summarize_mode(mode_name)
        except ValueError:
            continue
        print(
            f"{mode_name}: capacity={summary.total_cooling_capacity_kw:.1f} kW, "
            f"motor_power={summary.total_rated_motor_power_kw:.1f} kW, "
            f"equivalent_COP={summary.equivalent_cop:.2f}, "
            f"units={summary.active_unit_count}"
        )


def write_simulation_rows_with_fallback(path: Path, rows: list) -> Path:
    """Write simulation rows, using a timestamped file if the default is open."""
    try:
        write_dict_rows(path, rows)
        return path
    except PermissionError:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        fallback_path = path.with_name(f"{path.stem}_{timestamp}{path.suffix}")
        write_dict_rows(fallback_path, rows)
        return fallback_path


def build_user_csv_rows(rows: list) -> list[dict[str, float]]:
    """Build the compact CSV table requested by the user."""
    return [
        {
            "时间_h": row.time_s / 3600.0,
            "室外温度_C": row.outdoor_air_temperature_c,
            "室内温度_C": row.indoor_air_temperature_c,
            "供水管网温度_C": row.pipe_supply_temperature_c,
            "回水管网温度_C": row.pipe_return_temperature_c,
            "空调负荷_kW": row.q_cool_w / 1000.0,
            "室内物品热源热量_kW": row.q_thermal_mass_load_w / 1000.0,
            "室内总热量_kW": row.q_building_cooling_demand_w / 1000.0,
        }
        for row in rows
    ]


def run_connected_system() -> None:
    """Connect plant, supply/return pipe network, and building model."""
    run_cache = prepare_run_cache(PROJECT_ROOT)
    plant_config = load_json_config(PLANT_INPUT_PATH)
    plant_model = BasicPlantModel.from_config(plant_config)
    plant_output = plant_model.output()
    print_plant_summary(plant_model)

    pipe_config = load_json_config(NETWORK_INPUT_PATH)
    building_config = load_json_config(LOAD_INPUT_PATH)
    input_summary_path = run_cache / "figures" / "input_data_summary.png"
    export_input_data_summary_png(
        path=input_summary_path,
        plant_config=plant_config,
        pipe_config=pipe_config,
        building_config=building_config,
    )

    pipe_network = SupplyReturnPipeNetwork(PipeRCParameters(**pipe_config["model"]))
    pipe_state = PipePairState(
        supply=PipeRCState(
            water_temperature_c=pipe_config["initial_state"][
                "supply_water_temperature_c"
            ]
        ),
        return_=PipeRCState(
            water_temperature_c=pipe_config["initial_state"][
                "return_water_temperature_c"
            ]
        ),
    )

    building_model = BuildingRCModel(building_parameters_from_config(building_config))
    building_state = BuildingRCState(**building_config["initial_state"])
    schedules = building_config.get("schedules", {})

    rows = simulate_coupled_system(
        plant_output=plant_output,
        pipe_network=pipe_network,
        pipe_state=pipe_state,
        building_model=building_model,
        building_state=building_state,
        step_s=float(pipe_config["simulation"]["time_step_s"]),
        steps=int(pipe_config["simulation"]["steps"]),
        soil_temperature_c=pipe_config["inputs"]["soil_temperature_c"],
        mass_flow_kg_per_s=pipe_config["inputs"]["mass_flow_kg_per_s"],
        outdoor_air_temperature_c=building_config["inputs"][
            "outdoor_air_temperature_c"
        ],
        internal_load_w=building_config["inputs"]["internal_load_w"],
        internal_load_schedule=(
            make_daily_schedule(schedules["internal_load_w"])
            if "internal_load_w" in schedules
            else None
        ),
        solar_gain_w=building_config["inputs"].get("solar_gain_w", 0.0),
        solar_gain_schedule=(
            make_daily_schedule(schedules["solar_gain_w"])
            if "solar_gain_w" in schedules
            else None
        ),
        thermal_mass_load_w=building_config["inputs"].get("thermal_mass_load_w", 0.0),
        thermal_mass_load_schedule=(
            make_daily_schedule(schedules["thermal_mass_load_w"])
            if "thermal_mass_load_w" in schedules
            else None
        ),
        thermal_mass_heat_capacity_schedule=(
            make_daily_schedule(schedules["thermal_mass_heat_capacity_j_per_k"])
            if "thermal_mass_heat_capacity_j_per_k" in schedules
            else None
        ),
    )

    output_path = run_cache / "simulations" / "coupled_system_basic.csv"
    output_path = write_simulation_rows_with_fallback(
        output_path,
        build_user_csv_rows(rows),
    )
    result_paths = export_standard_results(
        figure_dir=run_cache / "figures",
        table_dir=run_cache / "tables",
        rows=rows,
    )

    print("Connected plant-pipe-building system finished.")
    print(f"Output: {output_path}")
    print("Result CSV and PNG files:")
    print(f"  input_data_summary: {input_summary_path}")
    for result_name, paths in result_paths.items():
        if "csv" in paths:
            print(f"  {result_name}: {paths['csv']} | {paths['png']}")
        else:
            print(f"  {result_name}: {paths['png']}")
    print(f"Initial Qcool: {rows[0].q_cool_w / 1000:.3f} kW")
    print(f"Final Qcool: {rows[-1].q_cool_w / 1000:.3f} kW")
    print(f"Final T_indoor: {rows[-1].indoor_air_temperature_c:.3f} degC")


def main() -> int:
    """Project-level runner."""
    run_connected_system()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
