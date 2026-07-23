import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from district_cooling.load import BuildingRCModel, BuildingRCParameters, BuildingRCState  # noqa: E402
from district_cooling.network import (  # noqa: E402
    PipePairState,
    PipeRCParameters,
    PipeRCState,
    SupplyReturnPipeNetwork,
)
from district_cooling.plant import BasicPlantOutput  # noqa: E402
from district_cooling.system import simulate_coupled_system  # noqa: E402


class CoupledSimulationTest(unittest.TestCase):
    def test_first_step_qcool_is_computed_from_pipe_temperatures(self) -> None:
        rows = simulate_coupled_system(
            plant_output=BasicPlantOutput(
                supply_water_temperature_c=4.0,
                return_water_temperature_c=9.0,
            ),
            pipe_network=SupplyReturnPipeNetwork(
                PipeRCParameters(
                    water_heat_capacity_j_per_k=2.5e8,
                    water_specific_heat_j_per_kg_k=4180.0,
                    pipe_length_m=5000.0,
                    pipe_thermal_resistance_k_m_per_w=0.01,
                )
            ),
            pipe_state=PipePairState(
                supply=PipeRCState(water_temperature_c=4.0),
                return_=PipeRCState(water_temperature_c=9.0),
            ),
            building_model=BuildingRCModel(
                BuildingRCParameters(
                    indoor_air_heat_capacity_j_per_k=3.0e6,
                    thermal_mass_heat_capacity_j_per_k=8.0e7,
                    outwall_thermal_resistance_k_per_w=0.003,
                    mass_thermal_resistance_k_per_w=0.0015,
                )
            ),
            building_state=BuildingRCState(
                indoor_air_temperature_c=26.0,
                thermal_mass_temperature_c=25.5,
            ),
            step_s=300.0,
            steps=1,
            soil_temperature_c=18.0,
            mass_flow_kg_per_s=100.0,
            outdoor_air_temperature_c=32.0,
            internal_load_w=4500.0,
        )

        self.assertAlmostEqual(rows[0].q_cool_w, 100.0 * 4180.0 * 5.0)
        self.assertAlmostEqual(rows[0].q_internal_load_w, 4500.0)
        self.assertAlmostEqual(rows[0].q_solar_gain_w, 0.0)
        self.assertAlmostEqual(rows[0].q_outwall_w, (32.0 - 26.0) / 0.003)
        self.assertAlmostEqual(rows[0].q_mass_to_air_w, (25.5 - 26.0) / 0.0015)
        expected_cooling_demand_w = rows[0].q_outwall_w + rows[0].q_solar_gain_w + rows[0].q_mass_to_air_w
        self.assertAlmostEqual(rows[0].q_building_cooling_demand_w, expected_cooling_demand_w)
        self.assertAlmostEqual(
            rows[0].calculated_building_return_temperature_c,
            4.0 + expected_cooling_demand_w / (100.0 * 4180.0),
        )


if __name__ == "__main__":
    unittest.main()
