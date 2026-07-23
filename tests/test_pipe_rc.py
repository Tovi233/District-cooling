import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from district_cooling.network import PipeRCInput, PipeRCModel, PipeRCParameters, PipeRCState  # noqa: E402
from district_cooling.simulation import simulate_fixed_step  # noqa: E402


class PipeRCModelTest(unittest.TestCase):
    def test_pipe_rc_equations(self) -> None:
        model = PipeRCModel(
            PipeRCParameters(
                water_heat_capacity_j_per_k=1000.0,
                pipe_thermal_resistance_k_per_w=0.5,
                water_specific_heat_j_per_kg_k=4.0,
            )
        )
        state = PipeRCState(water_temperature_c=10.0)
        inputs = PipeRCInput(
            inlet_temperature_c=8.0,
            soil_temperature_c=12.0,
            mass_flow_kg_per_s=3.0,
        )

        expected_q_flow = 3.0 * 4.0 * (8.0 - 10.0)
        expected_q_soil = (12.0 - 10.0) / 0.5
        expected_derivative = (expected_q_flow + expected_q_soil) / 1000.0

        self.assertAlmostEqual(model.q_flow_w(state, inputs), expected_q_flow)
        self.assertAlmostEqual(model.q_soil_w(state, inputs), expected_q_soil)
        self.assertAlmostEqual(
            model.derivative(state, inputs).water_temperature_c,
            expected_derivative,
        )

    def test_fixed_step_runner(self) -> None:
        model = PipeRCModel(
            PipeRCParameters(
                water_heat_capacity_j_per_k=2.5e8,
                pipe_thermal_resistance_k_per_w=2.0e-4,
            )
        )
        inputs = [
            PipeRCInput(
                inlet_temperature_c=7.0,
                soil_temperature_c=18.0,
                mass_flow_kg_per_s=100.0,
            )
            for _ in range(4)
        ]

        results = simulate_fixed_step(
            model=model,
            initial_state=PipeRCState(water_temperature_c=13.0),
            inputs=inputs,
            step_s=300.0,
        )

        self.assertEqual(len(results), 4)
        self.assertLess(results[-1][1].water_temperature_c, results[0][1].water_temperature_c)


if __name__ == "__main__":
    unittest.main()
