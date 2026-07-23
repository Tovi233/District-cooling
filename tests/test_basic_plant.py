import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
PLANT_INPUT_PATH = (
    PROJECT_ROOT / "src" / "district_cooling" / "plant" / "inputs" / "plant_basic.json"
)

from district_cooling.io import load_json_config  # noqa: E402
from district_cooling.plant import (  # noqa: E402
    BasicPlantModel,
    BasicPlantParameters,
    ChillerModeParameters,
    ChillerUnit,
)


class BasicPlantModelTest(unittest.TestCase):
    def test_output_returns_fixed_temperatures(self) -> None:
        model = BasicPlantModel(
            BasicPlantParameters(
                supply_water_temperature_c=7.0,
                return_water_temperature_c=12.0,
                chillers=(
                    ChillerUnit(
                        equipment_name="test_chiller",
                        quantity=1,
                        power_supply="380V",
                        modes=(
                            ChillerModeParameters(
                                mode_name="air_conditioning",
                                cooling_capacity_kw=1000.0,
                                rated_motor_power_kw=200.0,
                                cop=5.0,
                                chilled_water_temperature="12C/7C",
                                cooling_water_temperature="30C/35C",
                            ),
                        ),
                    ),
                ),
            )
        )

        output = model.output()

        self.assertAlmostEqual(output.supply_water_temperature_c, 7.0)
        self.assertAlmostEqual(output.return_water_temperature_c, 12.0)

    def test_return_temperature_should_not_be_lower_than_supply(self) -> None:
        with self.assertRaises(ValueError):
            BasicPlantModel(
                BasicPlantParameters(
                    supply_water_temperature_c=12.0,
                    return_water_temperature_c=7.0,
                    chillers=(
                        ChillerUnit(
                            equipment_name="test_chiller",
                            quantity=1,
                            power_supply="380V",
                            modes=(
                                ChillerModeParameters(
                                    mode_name="air_conditioning",
                                    cooling_capacity_kw=1000.0,
                                    rated_motor_power_kw=200.0,
                                    cop=5.0,
                                    chilled_water_temperature="12C/7C",
                                    cooling_water_temperature="30C/35C",
                                ),
                            ),
                        ),
                    ),
                )
            )

    def test_first_stage_air_conditioning_summary_matches_source_data(self) -> None:
        config = load_json_config(PLANT_INPUT_PATH)
        model = BasicPlantModel.from_config(config)

        summary = model.summarize_mode("air_conditioning")

        self.assertAlmostEqual(summary.total_cooling_capacity_kw, 20113.0)
        self.assertAlmostEqual(summary.total_rated_motor_power_kw, 3460.7)
        self.assertAlmostEqual(summary.equivalent_cop, 20113.0 / 3460.7)
        self.assertEqual(summary.active_unit_count, 4)

    def test_first_stage_ice_storage_summary_matches_source_data(self) -> None:
        config = load_json_config(PLANT_INPUT_PATH)
        model = BasicPlantModel.from_config(config)

        summary = model.summarize_mode("ice_storage")

        self.assertAlmostEqual(summary.total_cooling_capacity_kw, 12660.0)
        self.assertAlmostEqual(summary.total_rated_motor_power_kw, 3078.0)
        self.assertAlmostEqual(summary.equivalent_cop, 12660.0 / 3078.0)
        self.assertEqual(summary.active_unit_count, 3)


if __name__ == "__main__":
    unittest.main()
