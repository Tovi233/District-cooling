"""Utilities for aligning measured solar irradiance with measurement rows."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence


def _parse_timestamp(value: str) -> datetime:
    text = value.strip()
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y/%-m/%-d %H:%M:%S",
        "%Y/%-m/%-d %H:%M",
    ):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    return datetime.fromisoformat(text)


def maybe_add_solar_measurements(
    rows: Sequence[dict[str, str]],
    run_config: dict[str, Any],
    project_root: str | Path,
) -> list[dict[str, str]]:
    """Attach interpolated measured solar gain columns when configured."""
    solar_config = run_config.get("solar_measurement")
    if not solar_config:
        return [dict(row) for row in rows]

    root = Path(project_root)
    source_path = root / solar_config["source_csv_path"]
    points = _load_solar_points(source_path, solar_config)
    if len(points) < 2:
        raise ValueError("solar measurement file must contain at least two data rows")

    columns = run_config["columns"]
    time_column = columns["time"]
    irradiance_column = str(
        solar_config.get("output_irradiance_column", "measured_solar_irradiance_w_m2")
    )
    gain_column = str(
        solar_config.get(
            "output_gain_column",
            columns.get("measured_solar_gain_kw") or "measured_solar_gain_kw",
        )
    )
    area_m2 = float(solar_config.get("equivalent_solar_gain_area_m2", 1.0))

    enriched_rows: list[dict[str, str]] = []
    missing_count = 0
    for row in rows:
        enriched = dict(row)
        timestamp = _parse_timestamp(row[time_column])
        irradiance = _interpolate_solar_irradiance(points, timestamp)
        if irradiance is None:
            missing_count += 1
            enriched[irradiance_column] = ""
            enriched[gain_column] = ""
        else:
            solar_gain_kw = irradiance * area_m2 / 1000.0
            enriched[irradiance_column] = f"{irradiance:.9g}"
            enriched[gain_column] = f"{solar_gain_kw:.9g}"
        enriched_rows.append(enriched)

    if missing_count:
        raise ValueError(
            f"{missing_count} measurement rows are outside the solar data time range"
        )
    return enriched_rows


def _load_solar_points(
    source_path: Path,
    solar_config: dict[str, Any],
) -> list[tuple[datetime, float]]:
    encoding = str(solar_config.get("encoding", "utf-8-sig"))
    skip_rows = int(solar_config.get("skip_rows", 0))
    date_column = str(solar_config.get("date_column", "date"))
    time_column = str(solar_config.get("time_column", "time"))
    direct_column = solar_config.get("direct_irradiance_column")
    diffuse_column = solar_config.get("diffuse_irradiance_column")
    total_column = solar_config.get("total_irradiance_column")
    clip_negative = bool(solar_config.get("clip_negative", True))

    points: list[tuple[datetime, float]] = []
    with source_path.open("r", encoding=encoding, newline="") as file:
        for _ in range(skip_rows):
            next(file, None)
        reader = csv.DictReader(file)
        for row in reader:
            if not row.get(date_column) or not row.get(time_column):
                continue
            timestamp = _parse_timestamp(
                f"{row[date_column].strip()} {row[time_column].strip()}"
            )
            if total_column:
                irradiance = float(row[str(total_column)])
            else:
                irradiance = 0.0
                if direct_column:
                    irradiance += float(row[str(direct_column)])
                if diffuse_column:
                    irradiance += float(row[str(diffuse_column)])
            if clip_negative:
                irradiance = max(irradiance, 0.0)
            points.append((timestamp, irradiance))
    points.sort(key=lambda item: item[0])
    return points


def _interpolate_solar_irradiance(
    points: Sequence[tuple[datetime, float]],
    target: datetime,
) -> float | None:
    if target < points[0][0] or target > points[-1][0]:
        return None
    low = 0
    high = len(points) - 1
    while low <= high:
        mid = (low + high) // 2
        timestamp = points[mid][0]
        if timestamp < target:
            low = mid + 1
        elif timestamp > target:
            high = mid - 1
        else:
            return points[mid][1]

    upper = low
    lower = upper - 1
    if lower < 0 or upper >= len(points):
        return None
    lower_time, lower_value = points[lower]
    upper_time, upper_value = points[upper]
    span_s = (upper_time - lower_time).total_seconds()
    if span_s <= 0.0:
        return lower_value
    ratio = (target - lower_time).total_seconds() / span_s
    return lower_value + ratio * (upper_value - lower_value)
