"""CSV result writers."""

from __future__ import annotations

import csv
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Iterable, Any


def write_dataclass_rows(path: str | Path, rows: Iterable[Any]) -> None:
    """Write dataclass rows to CSV."""
    rows = list(rows)
    if not rows:
        raise ValueError("rows must not be empty")
    if not all(is_dataclass(row) for row in rows):
        raise TypeError("all rows must be dataclass instances")

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(asdict(rows[0]).keys())

    with output_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def write_dict_rows(
    path: str | Path,
    rows: Iterable[dict[str, Any]],
    fieldnames: list[str] | None = None,
) -> None:
    """Write dictionary rows to CSV."""
    rows = list(rows)
    if not rows:
        raise ValueError("rows must not be empty")

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = list(rows[0].keys())

    with output_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
