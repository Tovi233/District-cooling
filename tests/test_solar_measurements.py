import csv
import tempfile
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from district_cooling.load.solar_measurements import maybe_add_solar_measurements  # noqa: E402


class SolarMeasurementsTest(unittest.TestCase):
    def test_adds_interpolated_solar_gain_to_measurement_rows(self) -> None:
        rows = [
            {"time": "2025-07-08 10:15:00", "elapsed_h": "0.0"},
            {"time": "2025-07-08 10:30:00", "elapsed_h": "0.25"},
        ]
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            solar_path = root / "solar.csv"
            with solar_path.open("w", encoding="utf-8", newline="") as file:
                writer = csv.writer(file)
                writer.writerow(["metadata"])
                writer.writerow(["日期", "时间", "法向直接辐射W/m^2", "散射辐射W/m^2"])
                writer.writerow(["2025-07-08", "10:00:00", "100", "20"])
                writer.writerow(["2025-07-08", "11:00:00", "200", "40"])

            config = {
                "columns": {
                    "time": "time",
                    "measured_solar_gain_kw": "measured_solar_gain_kw",
                },
                "solar_measurement": {
                    "source_csv_path": "solar.csv",
                    "encoding": "utf-8",
                    "skip_rows": 1,
                    "date_column": "日期",
                    "time_column": "时间",
                    "direct_irradiance_column": "法向直接辐射W/m^2",
                    "diffuse_irradiance_column": "散射辐射W/m^2",
                    "output_irradiance_column": "measured_solar_irradiance_w_m2",
                    "output_gain_column": "measured_solar_gain_kw",
                    "equivalent_solar_gain_area_m2": 10.0,
                },
            }

            enriched = maybe_add_solar_measurements(rows, config, root)

        self.assertAlmostEqual(float(enriched[0]["measured_solar_irradiance_w_m2"]), 150.0)
        self.assertAlmostEqual(float(enriched[0]["measured_solar_gain_kw"]), 1.5)
        self.assertAlmostEqual(float(enriched[1]["measured_solar_irradiance_w_m2"]), 180.0)
        self.assertAlmostEqual(float(enriched[1]["measured_solar_gain_kw"]), 1.8)


if __name__ == "__main__":
    unittest.main()
