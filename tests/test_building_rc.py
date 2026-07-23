import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from district_cooling.load import (  # noqa: E402
    BuildingRCInput,
    BuildingRCModel,
    BuildingRCParameters,
    BuildingRCState,
    OfficeModule,
    building_parameters_from_config,
    estimate_office_interior_walls,
    materialize_building_model_config,
)
from district_cooling.simulation import simulate_fixed_step  # noqa: E402


class BuildingRCModelTest(unittest.TestCase):
    def test_building_rc_equations(self) -> None:
        model = BuildingRCModel(
            BuildingRCParameters(
                indoor_air_heat_capacity_j_per_k=1000.0,
                thermal_mass_heat_capacity_j_per_k=2000.0,
                outwall_thermal_resistance_k_per_w=0.5,
                mass_thermal_resistance_k_per_w=0.25,
            )
        )
        state = BuildingRCState(
            indoor_air_temperature_c=26.0,
            thermal_mass_temperature_c=24.0,
        )
        inputs = BuildingRCInput(
            outdoor_air_temperature_c=30.0,
            internal_load_w=100.0,
            solar_gain_w=50.0,
            cooling_power_w=40.0,
        )

        expected_q_outwall = (30.0 - 26.0) / 0.5
        expected_q_mass_to_air = (24.0 - 26.0) / 0.25
        expected_q_total = -40.0
        expected_d_indoor = (
            expected_q_outwall + expected_q_mass_to_air + expected_q_total
        ) / 1000.0
        expected_d_mass = (100.0 + 50.0 - expected_q_mass_to_air) / 2000.0

        derivative = model.derivative(state, inputs)

        self.assertAlmostEqual(model.q_outwall_w(state, inputs), expected_q_outwall)
        self.assertAlmostEqual(model.q_mass_to_air_w(state), expected_q_mass_to_air)
        self.assertAlmostEqual(model.q_total_w(inputs), expected_q_total)
        self.assertAlmostEqual(derivative.indoor_air_temperature_c, expected_d_indoor)
        self.assertAlmostEqual(derivative.thermal_mass_temperature_c, expected_d_mass)

    def test_fixed_step_runner(self) -> None:
        model = BuildingRCModel(
            BuildingRCParameters(
                indoor_air_heat_capacity_j_per_k=3.0e6,
                thermal_mass_heat_capacity_j_per_k=8.0e7,
                outwall_thermal_resistance_k_per_w=0.003,
                mass_thermal_resistance_k_per_w=0.0015,
            )
        )
        inputs = [
            BuildingRCInput(
                outdoor_air_temperature_c=32.0,
                internal_load_w=4500.0,
                cooling_power_w=5200.0,
            )
            for _ in range(4)
        ]

        results = simulate_fixed_step(
            model=model,
            initial_state=BuildingRCState(
                indoor_air_temperature_c=26.0,
                thermal_mass_temperature_c=25.5,
            ),
            inputs=inputs,
            step_s=300.0,
        )

        self.assertEqual(len(results), 4)
        self.assertIsInstance(results[-1][1], BuildingRCState)

    def test_cooling_power_from_pipe_temperatures(self) -> None:
        model = BuildingRCModel(
            BuildingRCParameters(
                indoor_air_heat_capacity_j_per_k=3.0e6,
                thermal_mass_heat_capacity_j_per_k=8.0e7,
                outwall_thermal_resistance_k_per_w=0.003,
                mass_thermal_resistance_k_per_w=0.0015,
            )
        )

        q_cool = model.cooling_power_from_pipe_temperatures_w(
            supply_water_temperature_c=4.0,
            return_water_temperature_c=9.0,
            mass_flow_kg_per_s=100.0,
            water_specific_heat_j_per_kg_k=4180.0,
        )

        self.assertAlmostEqual(q_cool, 2090e3)

    def test_mass_exchange_resistance_from_config(self) -> None:
        parameters = building_parameters_from_config(
            {
                "model": {
                    "indoor_air_heat_capacity_j_per_k": 3.0e6,
                    "thermal_mass_heat_capacity_j_per_k": 8.0e7,
                    "outwall_thermal_resistance_k_per_w": 0.003,
                    "mass_exchange": {
                        "heat_transfer_coefficient_w_per_m2_k": 7.0,
                        "heat_transfer_area_m2": 6000.0,
                    },
                }
            }
        )

        self.assertAlmostEqual(
            parameters.mass_thermal_resistance_k_per_w,
            1.0 / (7.0 * 6000.0),
        )

    def test_geometry_derived_parameters_from_config(self) -> None:
        config = {
            "model": {
                "geometry": {
                    "building_count": 1.0,
                    "floors_per_building": 25.0,
                    "total_floor_area_m2": 7500.0,
                    "floor_height_m": 3.5,
                },
                "indoor_air": {
                    "effective_volumetric_heat_capacity_j_per_m3_k": 90000.0,
                },
                "indoor_object_heat_capacity_per_floor_area_j_per_m2_k": 12000.0,
                "outwall_layer": {
                    "thickness_m": 0.2,
                    "thermal_conductivity_w_per_m_k": 1.4,
                },
                "mass_exchange": {
                    "heat_transfer_coefficient_w_per_m2_k": 7.0,
                    "heat_transfer_area_sources": [
                        "total_floor_area_m2",
                        "exterior_wall_area_m2",
                    ],
                },
                "thermal_mass_heat_capacity_layers": [
                    {
                        "area_source": "total_floor_area_m2",
                        "thickness_m": 0.2,
                        "density_kg_per_m3": 2400.0,
                        "specific_heat_j_per_kg_k": 880.0,
                    },
                    {
                        "area_source": "exterior_wall_area_m2",
                        "thickness_m": 0.2,
                        "density_kg_per_m3": 2400.0,
                        "specific_heat_j_per_kg_k": 880.0,
                    },
                ],
            }
        }

        resolved = materialize_building_model_config(config)
        parameters = building_parameters_from_config(config)
        expected_wall_area = 4.0 * 300.0**0.5 * 25.0 * 3.5
        expected_floor_area = 25.0 * 300.0
        expected_air_volume = expected_floor_area * 3.5
        expected_wall_heat_capacity = expected_wall_area * 0.2 * 2400.0 * 880.0
        expected_floor_heat_capacity = expected_floor_area * 0.2 * 2400.0 * 880.0
        expected_object_heat_capacity = 12000.0 * expected_floor_area

        self.assertAlmostEqual(
            resolved["derived_geometry"]["exterior_wall_area_m2"],
            expected_wall_area,
        )
        self.assertAlmostEqual(
            resolved["derived_geometry"]["indoor_air_volume_m3"],
            expected_air_volume,
        )
        self.assertAlmostEqual(
            parameters.indoor_air_heat_capacity_j_per_k,
            expected_air_volume * 90000.0,
        )
        self.assertAlmostEqual(
            parameters.outwall_thermal_resistance_k_per_w,
            0.2 / (1.4 * expected_wall_area),
        )
        self.assertAlmostEqual(
            parameters.mass_thermal_resistance_k_per_w,
            1.0 / (7.0 * (expected_floor_area + expected_wall_area)),
        )
        self.assertAlmostEqual(
            parameters.thermal_mass_heat_capacity_j_per_k,
            expected_object_heat_capacity
            + expected_floor_heat_capacity
            + expected_wall_heat_capacity,
        )

    def test_office_interior_wall_volume_estimator(self) -> None:
        estimate = estimate_office_interior_walls(
            floor_area_per_floor_m2=541.6666666666666,
            floor_count=12.0,
            floor_height_m=3.5,
            wall_thickness_m=0.1,
            office_module=OfficeModule(width_m=4.95, depth_m=5.70),
            plan_aspect_ratio=1.0,
        )
        plan_side = 541.6666666666666**0.5
        expected_length = (
            541.6666666666666 / 4.95
            + 541.6666666666666 / 5.70
            - 2.0 * plan_side
        )

        self.assertAlmostEqual(
            estimate.office_count_per_floor,
            541.6666666666666 / (4.95 * 5.70),
        )
        self.assertAlmostEqual(
            estimate.interior_wall_length_per_floor_m,
            expected_length,
        )
        self.assertAlmostEqual(
            estimate.interior_wall_volume_per_floor_m3,
            expected_length * 3.5 * 0.1,
        )
        self.assertAlmostEqual(
            estimate.total_interior_wall_volume_m3,
            expected_length * 3.5 * 0.1 * 12.0,
        )

    def test_geometry_materializes_office_interior_walls(self) -> None:
        config = {
            "model": {
                "geometry": {
                    "building_count": 1.0,
                    "floors_per_building": 12.0,
                    "total_floor_area_m2": 6500.0,
                    "floor_height_m": 3.5,
                },
                "interior_wall_estimation": {
                    "office_module": {
                        "width_m": 4.95,
                        "depth_m": 5.70,
                    },
                    "wall_thickness_m": 0.1,
                },
            }
        }

        resolved = materialize_building_model_config(config)
        derived = resolved["derived_geometry"]

        self.assertAlmostEqual(derived["floor_area_per_floor_m2"], 6500.0 / 12.0)
        self.assertAlmostEqual(
            derived["estimated_office_count_per_floor"],
            (6500.0 / 12.0) / (4.95 * 5.70),
        )
        self.assertGreater(derived["total_interior_wall_volume_m3"], 0.0)

    def test_interior_wall_heat_capacity_layer_uses_estimated_wall_area(self) -> None:
        config = {
            "model": {
                "geometry": {
                    "building_count": 1.0,
                    "floors_per_building": 12.0,
                    "total_floor_area_m2": 6500.0,
                    "floor_height_m": 3.5,
                },
                "indoor_air_heat_capacity_j_per_k": 1.0e9,
                "thermal_mass_heat_capacity_j_per_k": 1.0,
                "outwall_thermal_resistance_k_per_w": 1.0,
                "mass_thermal_resistance_k_per_w": 1.0,
                "interior_wall_estimation": {
                    "office_module": {
                        "width_m": 4.95,
                        "depth_m": 5.70,
                    },
                    "wall_thickness_m": 0.1,
                },
                "thermal_mass_heat_capacity_layers": [
                    {
                        "area_source": "interior_wall_area_m2",
                        "thickness_m": 0.1,
                        "density_kg_per_m3": 2400.0,
                        "specific_heat_j_per_kg_k": 880.0,
                    }
                ],
            }
        }

        resolved = materialize_building_model_config(config)
        parameters = building_parameters_from_config(config)
        expected_capacity = (
            resolved["derived_geometry"]["total_interior_wall_volume_m3"]
            * 2400.0
            * 880.0
        )

        self.assertAlmostEqual(
            parameters.thermal_mass_heat_capacity_j_per_k,
            1.0 + expected_capacity,
        )


if __name__ == "__main__":
    unittest.main()
