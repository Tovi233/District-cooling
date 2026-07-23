import tempfile
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from district_cooling.results import (  # noqa: E402
    export_building_ac_load_png,
    export_input_data_summary_png,
    export_standard_results,
    extract_building_ac_load,
)
from district_cooling.system import CoupledSystemSample  # noqa: E402


class BuildingOutputsTest(unittest.TestCase):
    def test_extract_building_ac_load(self) -> None:
        rows = [
            CoupledSystemSample(
                time_s=0.0,
                plant_supply_temperature_c=4.0,
                plant_return_temperature_c=9.0,
                pipe_supply_temperature_c=4.0,
                pipe_return_temperature_c=9.0,
                mass_flow_kg_per_s=100.0,
                outdoor_air_temperature_c=32.0,
                q_cool_w=2090e3,
                q_internal_load_w=1500e3,
                q_solar_gain_w=0.0,
                q_outwall_w=300e3,
                q_mass_to_air_w=100e3,
                q_total_direct_air_w=-590e3,
                q_building_cooling_demand_w=1900e3,
                q_thermal_mass_load_w=200e3,
                thermal_mass_heat_capacity_j_per_k=8.0e10,
                calculated_building_return_temperature_c=9.0,
                indoor_air_temperature_c=26.0,
                thermal_mass_temperature_c=25.5,
                supply_pipe_heat_gain_w=0.0,
                return_pipe_heat_gain_w=0.0,
            )
        ]

        points = extract_building_ac_load(rows)

        self.assertEqual(len(points), 1)
        self.assertAlmostEqual(points[0].q_cool_kw, 2090.0)

    def test_export_png(self) -> None:
        points = extract_building_ac_load(
            [
                CoupledSystemSample(
                    time_s=0.0,
                    plant_supply_temperature_c=4.0,
                    plant_return_temperature_c=9.0,
                    pipe_supply_temperature_c=4.0,
                    pipe_return_temperature_c=9.0,
                    mass_flow_kg_per_s=100.0,
                    outdoor_air_temperature_c=32.0,
                    q_cool_w=2090e3,
                    q_internal_load_w=1500e3,
                    q_solar_gain_w=0.0,
                    q_outwall_w=300e3,
                    q_mass_to_air_w=100e3,
                    q_total_direct_air_w=-590e3,
                    q_building_cooling_demand_w=1900e3,
                    q_thermal_mass_load_w=200e3,
                    thermal_mass_heat_capacity_j_per_k=8.0e10,
                    calculated_building_return_temperature_c=9.0,
                    indoor_air_temperature_c=26.0,
                    thermal_mass_temperature_c=25.5,
                    supply_pipe_heat_gain_w=0.0,
                    return_pipe_heat_gain_w=0.0,
                )
            ]
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            png_path = Path(tmp_dir) / "building_ac_load.png"

            export_building_ac_load_png(png_path, points)

            self.assertEqual(png_path.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

    def test_export_standard_results(self) -> None:
        rows = [
            CoupledSystemSample(
                time_s=0.0,
                plant_supply_temperature_c=4.0,
                plant_return_temperature_c=9.0,
                pipe_supply_temperature_c=4.0,
                pipe_return_temperature_c=9.0,
                mass_flow_kg_per_s=100.0,
                outdoor_air_temperature_c=32.0,
                q_cool_w=2090e3,
                q_internal_load_w=1500e3,
                q_solar_gain_w=0.0,
                q_outwall_w=300e3,
                q_mass_to_air_w=100e3,
                q_total_direct_air_w=-590e3,
                q_building_cooling_demand_w=1900e3,
                q_thermal_mass_load_w=200e3,
                thermal_mass_heat_capacity_j_per_k=8.0e10,
                calculated_building_return_temperature_c=9.0,
                indoor_air_temperature_c=26.0,
                thermal_mass_temperature_c=25.5,
                supply_pipe_heat_gain_w=100e3,
                return_pipe_heat_gain_w=50e3,
            )
        ]
        with tempfile.TemporaryDirectory() as tmp_dir:
            paths = export_standard_results(
                figure_dir=Path(tmp_dir) / "figures",
                table_dir=Path(tmp_dir) / "tables",
                rows=rows,
            )

            self.assertEqual(
                set(paths),
                {
                    "internal_heat_source",
                    "outwall_heat_gain",
                    "solar_gain",
                    "air_conditioning_load",
                    "building_cooling_demand",
                    "supply_pipe_loss",
                    "return_pipe_loss",
                    "calculated_outputs_summary",
                },
            )
            for result_name, result_paths in paths.items():
                if result_name == "calculated_outputs_summary":
                    self.assertEqual(result_paths["png"].read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
                    continue
                self.assertIn("time_s", result_paths["csv"].read_text(encoding="utf-8"))
                self.assertEqual(result_paths["png"].read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

    def test_export_input_data_summary_png(self) -> None:
        plant_config = {
            "model": {
                "supply_water_temperature_c": 4.0,
                "chillers": [
                    {
                        "equipment_name": "dual_duty_chiller",
                        "quantity": 3,
                        "power_supply": "10kV",
                        "modes": [
                            {
                                "mode_name": "air_conditioning",
                                "cooling_capacity_kw": 5415.0,
                                "rated_motor_power_kw": 928.4,
                                "cop": 5.83,
                                "chilled_water_temperature": "11C/6C",
                                "cooling_water_temperature": "31C/36C",
                            }
                        ],
                    }
                ],
            }
        }
        pipe_config = {
            "model": {
                "water_heat_capacity_j_per_k": 2.5e8,
                "water_specific_heat_j_per_kg_k": 4180.0,
                "pipe_length_m": 5000.0,
                "pipe_thermal_resistance_k_m_per_w": 0.01,
            },
            "initial_state": {
                "supply_water_temperature_c": 4.0,
                "return_water_temperature_c": 9.0,
            },
            "simulation": {"time_step_s": 300.0, "steps": 288},
            "inputs": {"soil_temperature_c": 18.0, "mass_flow_kg_per_s": 100.0},
        }
        building_config = {
            "model": {
                "indoor_air_heat_capacity_j_per_k": 3.0e9,
                "thermal_mass_heat_capacity_j_per_k": 8.0e10,
                "outwall_thermal_resistance_k_per_w": 0.003,
                "mass_thermal_resistance_k_per_w": 0.0015,
            },
            "initial_state": {
                "indoor_air_temperature_c": 26.0,
                "thermal_mass_temperature_c": 25.5,
            },
            "inputs": {
                "outdoor_air_temperature_c": 32.0,
                "internal_load_w": 1500e3,
                "solar_gain_w": 0.0,
                "thermal_mass_load_w": 200e3,
            },
            "schedules": {
                "internal_load_w": [
                    {"time_h": 0, "value": 900e3},
                    {"time_h": 24, "value": 900e3},
                ],
                "solar_gain_w": [
                    {"time_h": 0, "value": 0.0},
                    {"time_h": 12, "value": 800e3},
                    {"time_h": 24, "value": 0.0},
                ],
            },
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            png_path = Path(tmp_dir) / "input_data_summary.png"

            export_input_data_summary_png(
                png_path,
                plant_config=plant_config,
                pipe_config=pipe_config,
                building_config=building_config,
            )

            self.assertEqual(png_path.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")


if __name__ == "__main__":
    unittest.main()
