import math
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from district_cooling.calibration.optimizer import coordinate_search  # noqa: E402
from district_cooling.calibration.optimizer import scipy_differential_evolution_l_bfgs_b  # noqa: E402
from district_cooling.calibration.building_calibrator import _prior_rc_ranges  # noqa: E402
from district_cooling.calibration.objective import (  # noqa: E402
    detect_temperature_period,
    split_rows_covering_min_duration,
    structured_parameters,
)
from district_cooling.calibration.parameter_space import (  # noqa: E402
    CalibrationParameter,
    parameters_for_level,
    recommended_level,
)


class CalibrationTest(unittest.TestCase):
    def test_recommended_level_depends_on_duration(self) -> None:
        self.assertEqual(recommended_level(12.0, requested_max_level=3), 1)
        self.assertEqual(recommended_level(48.0, requested_max_level=3), 2)
        self.assertEqual(recommended_level(96.0, requested_max_level=3), 3)
        self.assertEqual(recommended_level(96.0, requested_max_level=2), 2)

    def test_parameters_for_level_with_overrides(self) -> None:
        parameters = parameters_for_level(
            2,
            overrides={"k_C_m": {"initial": 1.2, "min": 0.5, "max": 2.0}},
        )
        names = [parameter.name for parameter in parameters]

        self.assertEqual(names, ["k_R_outwall", "k_C_m"])
        c_m = next(parameter for parameter in parameters if parameter.name == "k_C_m")
        self.assertAlmostEqual(c_m.initial, 1.2)
        self.assertAlmostEqual(c_m.lower, 0.5)
        self.assertAlmostEqual(c_m.upper, 2.0)

    def test_coordinate_search_reduces_simple_objective(self) -> None:
        parameters = [
            CalibrationParameter("k_R_outwall", 0.5, 3.0),
            CalibrationParameter("k_C_m", 0.3, 3.0),
        ]

        def objective(values: dict[str, float]) -> float:
            return (
                math.log(values["k_R_outwall"] / 1.4) ** 2
                + math.log(values["k_C_m"] / 0.9) ** 2
            )

        result = coordinate_search(parameters, objective, max_iterations=10)

        self.assertLess(result.best_loss, objective({"k_R_outwall": 1.0, "k_C_m": 1.0}))
        self.assertLess(abs(result.best_values["k_R_outwall"] - 1.4), 0.25)
        self.assertLess(abs(result.best_values["k_C_m"] - 0.9), 0.15)

    def test_scipy_optimizer_reduces_simple_objective(self) -> None:
        parameters = [
            CalibrationParameter("R_outwall", 1.0e-5, 1.0e-4, 3.0e-5),
            CalibrationParameter("C_m", 1.0e10, 2.0e11, 7.0e10),
        ]

        def objective(values: dict[str, float]) -> float:
            return (
                math.log(values["R_outwall"] / 4.0e-5) ** 2
                + math.log(values["C_m"] / 9.0e10) ** 2
            )

        result = scipy_differential_evolution_l_bfgs_b(
            parameters,
            objective,
            max_iterations=4,
            population_size=4,
            seed=1,
        )

        self.assertLess(result.best_loss, objective({"R_outwall": 3.0e-5, "C_m": 7.0e10}))
        self.assertLess(abs(result.best_values["R_outwall"] / 4.0e-5 - 1.0), 0.2)
        self.assertLess(abs(result.best_values["C_m"] / 9.0e10 - 1.0), 0.2)

    def test_split_rows_covering_min_duration_extends_training_segment(self) -> None:
        rows = [{"elapsed_h": str(hour)} for hour in range(0, 49)]

        train_rows, validation_rows = split_rows_covering_min_duration(
            rows,
            train_fraction=0.3,
            elapsed_column="elapsed_h",
            min_train_duration_h=24.0,
        )

        self.assertGreaterEqual(
            float(train_rows[-1]["elapsed_h"]) - float(train_rows[0]["elapsed_h"]),
            24.0,
        )
        self.assertGreaterEqual(len(validation_rows), 1)

    def test_detect_temperature_period_with_irregular_sampling(self) -> None:
        rows = []
        time_h = 0.0
        step_pattern = [0.25, 0.5, 1.0, 0.75]
        index = 0
        while time_h <= 96.0:
            temperature = 27.0 + 2.0 * math.sin(2.0 * math.pi * time_h / 24.0)
            rows.append(
                {
                    "elapsed_h": f"{time_h:.6f}",
                    "temperature_c": f"{temperature:.6f}",
                }
            )
            time_h += step_pattern[index % len(step_pattern)]
            index += 1

        result = detect_temperature_period(
            rows,
            elapsed_column="elapsed_h",
            temperature_column="temperature_c",
        )

        self.assertAlmostEqual(result.period_h, 24.0, delta=2.0)
        self.assertGreater(result.confidence, 0.25)

    def test_building_type_prior_maps_source_u_to_project_r(self) -> None:
        category = {
            "source": {
                "U_z": {"min": 2.0, "max": 10.0, "mean": 5.0},
                "U_1": {"min": 4.0, "max": 20.0, "mean": 10.0},
                "C_1": {"min": 100.0, "max": 200.0, "mean": 150.0},
                "Cin": {"min": 10.0, "max": 20.0, "mean": 15.0},
            }
        }

        ranges = _prior_rc_ranges(category)

        self.assertAlmostEqual(ranges["R_outwall"]["min"], 0.1)
        self.assertAlmostEqual(ranges["R_outwall"]["max"], 0.5)
        self.assertAlmostEqual(ranges["R_outwall"]["mean"], 0.2)
        self.assertAlmostEqual(ranges["R_m"]["mean"], 0.1)
        self.assertAlmostEqual(ranges["C_m"]["mean"], 150.0)
        self.assertAlmostEqual(ranges["C_indoor"]["mean"], 15.0)

    def test_structured_parameters_preserve_physical_coupling(self) -> None:
        building_config = {
            "model": {
                "geometry": {
                    "building_count": 1.0,
                    "floors_per_building": 10.0,
                    "total_floor_area_m2": 3000.0,
                    "floor_height_m": 3.5,
                },
                "indoor_air": {
                    "effective_volumetric_heat_capacity_j_per_m3_k": 90000.0,
                },
                "thermal_mass_heat_capacity_per_floor_area_j_per_m2_k": 1.0e7,
                "outwall_layer": {
                    "thickness_m": 0.2,
                    "thermal_conductivity_w_per_m_k": 1.4,
                },
                "mass_exchange": {
                    "heat_transfer_coefficient_w_per_m2_k": 14.0,
                },
            }
        }
        values = {
            "wall_thickness_m": 0.2,
            "wall_lambda_w_per_m_k": 1.0,
            "wall_volumetric_heat_capacity_j_per_m3_k": 2.0e6,
            "thermal_mass_heat_capacity_per_floor_area_j_per_m2_k": 1.0e7,
            "mass_exchange_h_w_per_m2_k": 10.0,
        }

        parameters = structured_parameters(building_config, values)
        thicker_values = dict(values)
        thicker_values["wall_thickness_m"] = 0.4
        thicker_parameters = structured_parameters(building_config, thicker_values)

        self.assertAlmostEqual(
            thicker_parameters.outwall_thermal_resistance_k_per_w
            / parameters.outwall_thermal_resistance_k_per_w,
            2.0,
        )
        self.assertGreater(
            thicker_parameters.thermal_mass_heat_capacity_j_per_k,
            parameters.thermal_mass_heat_capacity_j_per_k,
        )
        self.assertGreater(
            thicker_parameters.mass_thermal_resistance_k_per_w,
            parameters.mass_thermal_resistance_k_per_w,
        )

        thicker_floor_values = dict(values)
        thicker_floor_values["floor_slab_thickness_m"] = 0.4
        thicker_floor_parameters = structured_parameters(
            building_config,
            thicker_floor_values,
        )

        self.assertGreater(
            thicker_floor_parameters.thermal_mass_heat_capacity_j_per_k,
            parameters.thermal_mass_heat_capacity_j_per_k,
        )
        self.assertGreater(
            thicker_floor_parameters.mass_thermal_resistance_k_per_w,
            parameters.mass_thermal_resistance_k_per_w,
        )


if __name__ == "__main__":
    unittest.main()
