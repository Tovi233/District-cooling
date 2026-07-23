import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from district_cooling.system import CoolingLoadBalanceInput, calculate_load_balance  # noqa: E402


class CoolingLoadBalanceTest(unittest.TestCase):
    def test_load_and_pipe_heat_gain(self) -> None:
        result = calculate_load_balance(
            CoolingLoadBalanceInput(
                supply_water_temperature_c=4.0,
                return_water_temperature_c=9.0,
                soil_temperature_c=18.0,
                mass_flow_kg_per_s=100.0,
                pipe_length_m=5000.0,
                pipe_thermal_resistance_k_m_per_w=0.01,
                water_specific_heat_j_per_kg_k=4180.0,
            )
        )

        self.assertAlmostEqual(result.terminal_cooling_load_kw, 2090.0)
        self.assertAlmostEqual(result.pipe_heat_gain_kw, 5750.0)
        self.assertAlmostEqual(result.plant_required_cooling_kw, 7840.0)
        self.assertAlmostEqual(result.average_pipe_water_temperature_c, 6.5)


if __name__ == "__main__":
    unittest.main()
