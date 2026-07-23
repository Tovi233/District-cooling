import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from district_cooling.load import heuristic_thermal_mass_initial_temperature_c  # noqa: E402


class InitialStateHeuristicTest(unittest.TestCase):
    def test_clock_hour_offset_is_interpolated(self) -> None:
        temperature = heuristic_thermal_mass_initial_temperature_c(
            indoor_air_temperature_c=26.0,
            clock_hour=12.0,
            config={
                "clock_hour_offsets": [
                    {"start_hour": 10.0, "offset_c": 1.0},
                    {"start_hour": 14.0, "offset_c": 2.0},
                ]
            },
        )

        self.assertAlmostEqual(temperature, 27.5)

    def test_offset_is_clamped(self) -> None:
        temperature = heuristic_thermal_mass_initial_temperature_c(
            indoor_air_temperature_c=26.0,
            clock_hour=14.0,
            config={
                "clock_hour_offsets": [{"start_hour": 14.0, "offset_c": 5.0}],
                "maximum_offset_c": 2.0,
            },
        )

        self.assertAlmostEqual(temperature, 28.0)


if __name__ == "__main__":
    unittest.main()
