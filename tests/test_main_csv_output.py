import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from district_cooling.system import CoupledSystemSample  # noqa: E402
from main import build_user_csv_rows  # noqa: E402


class MainCsvOutputTest(unittest.TestCase):
    def test_user_csv_rows_only_include_requested_columns(self) -> None:
        rows = [
            CoupledSystemSample(
                time_s=3600.0,
                plant_supply_temperature_c=4.0,
                plant_return_temperature_c=9.0,
                pipe_supply_temperature_c=4.5,
                pipe_return_temperature_c=8.8,
                mass_flow_kg_per_s=100.0,
                outdoor_air_temperature_c=32.0,
                q_cool_w=1800e3,
                q_internal_load_w=1500e3,
                q_solar_gain_w=0.0,
                q_outwall_w=300e3,
                q_mass_to_air_w=50e3,
                q_total_direct_air_w=-300e3,
                q_building_cooling_demand_w=1850e3,
                q_thermal_mass_load_w=200e3,
                thermal_mass_heat_capacity_j_per_k=8.0e10,
                calculated_building_return_temperature_c=8.8,
                indoor_air_temperature_c=26.0,
                thermal_mass_temperature_c=25.5,
                supply_pipe_heat_gain_w=100e3,
                return_pipe_heat_gain_w=50e3,
            )
        ]

        output_rows = build_user_csv_rows(rows)

        self.assertEqual(
            list(output_rows[0]),
            [
                "时间_h",
                "室外温度_C",
                "室内温度_C",
                "供水管网温度_C",
                "回水管网温度_C",
                "空调负荷_kW",
                "室内物品热源热量_kW",
                "室内总热量_kW",
            ],
        )
        self.assertAlmostEqual(output_rows[0]["空调负荷_kW"], 1800.0)
        self.assertAlmostEqual(output_rows[0]["室内总热量_kW"], 1850.0)


if __name__ == "__main__":
    unittest.main()
