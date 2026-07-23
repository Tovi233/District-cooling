"""Run the basic pipe-network RC example."""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from district_cooling.io import load_json_config, write_dataclass_rows  # noqa: E402
from district_cooling.network import PipeRCInput, PipeRCModel, PipeRCParameters, PipeRCState  # noqa: E402


def build_inputs(config: dict) -> list[PipeRCInput]:
    input_config = config["inputs"]
    steps = int(config["simulation"]["steps"])
    pipe_input = PipeRCInput(
        inlet_temperature_c=float(input_config["inlet_temperature_c"]),
        soil_temperature_c=float(input_config["soil_temperature_c"]),
        mass_flow_kg_per_s=float(input_config["mass_flow_kg_per_s"]),
    )
    return [pipe_input for _ in range(steps)]


def main() -> int:
    config = load_json_config(
        PROJECT_ROOT
        / "src"
        / "district_cooling"
        / "network"
        / "inputs"
        / "pipe_network_basic.json"
    )
    model = PipeRCModel(PipeRCParameters(**config["model"]))
    state = PipeRCState(
        water_temperature_c=float(config["initial_state"]["water_temperature_c"])
    )
    step_s = float(config["simulation"]["time_step_s"])
    inputs = build_inputs(config)

    rows = []
    for index, current_input in enumerate(inputs):
        time_s = index * step_s
        rows.append(model.sample(time_s, state, current_input))
        state = model.step(state, current_input, step_s)

    output_path = PROJECT_ROOT / "outputs" / "simulations" / "pipe_network_basic.csv"
    write_dataclass_rows(output_path, rows)

    print(f"saved: {output_path}")
    print(f"initial Tw: {rows[0].water_temperature_c:.3f} degC")
    print(f"final Tw: {rows[-1].water_temperature_c:.3f} degC")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
