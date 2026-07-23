import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from district_cooling.network import (  # noqa: E402
    PipePairInput,
    PipePairState,
    PipeRCParameters,
    PipeRCState,
    SupplyReturnPipeNetwork,
)


class SupplyReturnPipeNetworkTest(unittest.TestCase):
    def test_terminal_cooling_power_uses_supply_and_return_pipes(self) -> None:
        network = SupplyReturnPipeNetwork(
            PipeRCParameters(
                water_heat_capacity_j_per_k=2.5e8,
                water_specific_heat_j_per_kg_k=4180.0,
                pipe_length_m=5000.0,
                pipe_thermal_resistance_k_m_per_w=0.01,
            )
        )
        state = PipePairState(
            supply=PipeRCState(water_temperature_c=4.0),
            return_=PipeRCState(water_temperature_c=9.0),
        )
        inputs = PipePairInput(
            supply_inlet_temperature_c=4.0,
            return_inlet_temperature_c=9.0,
            soil_temperature_c=18.0,
            mass_flow_kg_per_s=100.0,
        )

        q_cool = network.terminal_cooling_power_w(state, inputs)

        self.assertAlmostEqual(q_cool, 100.0 * 4180.0 * (9.0 - 4.0))


if __name__ == "__main__":
    unittest.main()
