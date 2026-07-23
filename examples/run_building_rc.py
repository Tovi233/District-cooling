"""Run the basic building RC example."""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from district_cooling.io import load_json_config, write_dataclass_rows  # noqa: E402
from district_cooling.load import (  # noqa: E402
    BuildingRCInput,
    BuildingRCModel,
    BuildingRCState,
    building_parameters_from_config,
)


def main() -> int:
    config = load_json_config(
        PROJECT_ROOT / "src" / "district_cooling" / "load" / "inputs" / "building_basic.json"
    )
    model = BuildingRCModel(building_parameters_from_config(config))
    state = BuildingRCState(**config["initial_state"])
    step_s = float(config["simulation"]["time_step_s"])
    steps = int(config["simulation"]["steps"])
    inputs = BuildingRCInput(**config["inputs"])

    rows = []
    for index in range(steps):
        time_s = index * step_s
        rows.append(model.sample(time_s, state, inputs))
        state = model.step(state, inputs, step_s)

    output_path = PROJECT_ROOT / "outputs" / "simulations" / "building_basic.csv"
    write_dataclass_rows(output_path, rows)

    print(f"saved: {output_path}")
    print(f"initial T_indoor: {rows[0].indoor_air_temperature_c:.3f} degC")
    print(f"final T_indoor: {rows[-1].indoor_air_temperature_c:.3f} degC")
    print(f"final T_mass: {rows[-1].thermal_mass_temperature_c:.3f} degC")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
