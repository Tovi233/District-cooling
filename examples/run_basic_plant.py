"""Run the central plant parameter example."""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from district_cooling.io import load_json_config  # noqa: E402
from district_cooling.plant import BasicPlantModel  # noqa: E402


def main() -> int:
    config = load_json_config(
        PROJECT_ROOT / "src" / "district_cooling" / "plant" / "inputs" / "plant_basic.json"
    )
    model = BasicPlantModel.from_config(config)
    output = model.output()

    print(f"supply water temperature: {output.supply_water_temperature_c:.3f} degC")
    if output.return_water_temperature_c is None:
        print("return water temperature: calculated by building and return pipe")
    else:
        print(f"return water temperature: {output.return_water_temperature_c:.3f} degC")
    for mode_name in ("air_conditioning", "ice_storage", "nominal"):
        try:
            summary = model.summarize_mode(mode_name)
        except ValueError:
            continue
        print(
            f"{summary.mode_name}: "
            f"capacity={summary.total_cooling_capacity_kw:.1f} kW, "
            f"motor_power={summary.total_rated_motor_power_kw:.1f} kW, "
            f"equivalent_COP={summary.equivalent_cop:.2f}, "
            f"units={summary.active_unit_count}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
