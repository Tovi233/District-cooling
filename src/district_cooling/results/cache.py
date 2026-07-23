"""Runtime cache management for generated results."""

from __future__ import annotations

from pathlib import Path


CACHE_SUBDIRS = ("figures", "tables", "simulations")
CACHE_README = """# Run Cache

This folder stores the latest calculation outputs and figures.

It is temporary. Running `main.py` clears this folder and writes fresh results.
Copy files elsewhere before the next run if you want to keep them.

If an old file is open in another program, Windows may keep it locked. In that
case the locked file is left in place and the new run continues.
"""


def _remove_if_available(path: Path) -> bool:
    """Remove a cache path if Windows is not holding it open."""
    try:
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            path.rmdir()
    except (OSError, PermissionError):
        return False
    return True


def prepare_run_cache(project_root: str | Path) -> Path:
    """Clear and recreate the runtime cache folder for a new calculation.

    The cache is intentionally temporary: every main calculation starts with a
    clean cache unless the user has manually copied results elsewhere.
    """
    root = Path(project_root)
    cache_dir = root / "run_cache"
    cache_dir.mkdir(exist_ok=True)

    for child in cache_dir.iterdir():
        if child.is_dir():
            for nested in sorted(child.rglob("*"), reverse=True):
                _remove_if_available(nested)
            _remove_if_available(child)
        else:
            _remove_if_available(child)

    for subdir in CACHE_SUBDIRS:
        (cache_dir / subdir).mkdir(parents=True, exist_ok=True)
    (cache_dir / "README.md").write_text(CACHE_README, encoding="utf-8")

    return cache_dir
