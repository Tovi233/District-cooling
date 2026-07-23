"""Calculate terminal cooling load and pipe heat gain."""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from district_cooling.io import load_json_config  # noqa: E402
from district_cooling.system import CoolingLoadBalanceInput, calculate_load_balance  # noqa: E402


def main() -> int:
    plant_config = load_json_config(
        PROJECT_ROOT / "src" / "district_cooling" / "plant" / "inputs" / "plant_basic.json"
    )
    pipe_config = load_json_config(
        PROJECT_ROOT
        / "src"
        / "district_cooling"
        / "network"
        / "inputs"
        / "pipe_network_basic.json"
    )

    inputs = CoolingLoadBalanceInput(
        supply_water_temperature_c=plant_config["model"]["supply_water_temperature_c"],
        return_water_temperature_c=pipe_config["initial_state"]["return_water_temperature_c"],
        soil_temperature_c=pipe_config["inputs"]["soil_temperature_c"],
        mass_flow_kg_per_s=pipe_config["inputs"]["mass_flow_kg_per_s"],
        pipe_length_m=pipe_config["model"]["pipe_length_m"],
        pipe_thermal_resistance_k_m_per_w=pipe_config["model"][
            "pipe_thermal_resistance_k_m_per_w"
        ],
        water_specific_heat_j_per_kg_k=pipe_config["model"][
            "water_specific_heat_j_per_kg_k"
        ],
    )
    result = calculate_load_balance(inputs)

    print(f"terminal cooling load: {result.terminal_cooling_load_kw:.3f} kW")
    print(f"pipe heat gain/loss: {result.pipe_heat_gain_kw:.3f} kW")
    print(f"plant required cooling: {result.plant_required_cooling_kw:.3f} kW")
    print(
        "average pipe water temperature: "
        f"{result.average_pipe_water_temperature_c:.3f} degC"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
