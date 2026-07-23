import csv
import tempfile
import sys
import unittest
from pathlib import Path

from openpyxl import Workbook


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from district_cooling.load.measurement_import import import_wzs_measurements  # noqa: E402


class MeasurementImportTest(unittest.TestCase):
    def test_import_wzs_measurements_writes_normalized_csv(self) -> None:
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.append(
            [
                "时间",
                "#01冷机电功率(kW)",
                "#02冷机电功率(kW)",
                "冷机总功率(kW)",
                "水流量(m3/h)",
                "供水温度(℃)",
                "回水温度(℃)",
                "冷负荷(kW)",
                "室外温度(℃)",
                "室外相对湿度(%)",
                "室内平均温度(℃)",
                "室内平均相对湿度(%)",
                "室内温度F4(℃)",
                "室内相对湿度F4(%)",
                "室内温度F6(℃)",
                "室内相对湿度F6(%)",
                "室内温度F11(℃)",
                "室内相对湿度F11(%)",
            ]
        )
        worksheet.append(
            [
                "2025-07-08 10:15:00",
                91.5,
                0.2,
                91.7,
                65.1,
                7.5,
                12.5,
                372.5,
                32.0,
                70.7,
                27.6,
                58.4,
                27.4,
                56.5,
                27.1,
                59.7,
                28.3,
                59.0,
            ]
        )
        worksheet.append(
            [
                "2025-07-08 10:30:00",
                88.1,
                0.2,
                88.3,
                65.0,
                7.7,
                12.4,
                353.9,
                32.3,
                69.8,
                27.7,
                58.2,
                27.4,
                57.9,
                27.3,
                59.9,
                28.3,
                56.7,
            ]
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            source_path = Path(tmp_dir) / "measurements.xlsx"
            output_path = Path(tmp_dir) / "measurements.csv"
            workbook.save(source_path)

            summary = import_wzs_measurements(source_path, output_path)

            self.assertEqual(summary.row_count, 2)
            self.assertAlmostEqual(summary.time_step_s, 900.0)
            with output_path.open("r", encoding="utf-8-sig", newline="") as file:
                rows = list(csv.DictReader(file))
            self.assertEqual(rows[0]["time"], "2025-07-08 10:15:00")
            self.assertEqual(rows[1]["elapsed_h"], "0.25")
            self.assertEqual(rows[0]["cooling_load_kw"], "372.5")
            self.assertEqual(rows[0]["indoor_average_temperature_c"], "27.6")


if __name__ == "__main__":
    unittest.main()
