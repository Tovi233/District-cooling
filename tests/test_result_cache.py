import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from district_cooling.results import prepare_run_cache  # noqa: E402


class ResultCacheTest(unittest.TestCase):
    def test_prepare_run_cache_clears_previous_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            old_file = root / "run_cache" / "tables" / "old.csv"
            old_file.parent.mkdir(parents=True)
            old_file.write_text("old", encoding="utf-8")

            cache_dir = prepare_run_cache(root)

            self.assertFalse(old_file.exists())
            self.assertTrue((cache_dir / "figures").is_dir())
            self.assertTrue((cache_dir / "tables").is_dir())
            self.assertTrue((cache_dir / "simulations").is_dir())
            self.assertTrue((cache_dir / "README.md").is_file())


if __name__ == "__main__":
    unittest.main()
