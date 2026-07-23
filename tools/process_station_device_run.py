"""Prepare station device run CSV metadata and normalized data files."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any


NUMERIC_COLUMNS = [
    "status",
    "power_kw",
    "freq_hz",
    "chw_in_temp",
    "chw_out_temp",
    "cw_in_temp",
    "cw_out_temp",
    "setpoint_temp",
    "valve_open",
    "inventory_rt",
    "flow_m3h",
    "cooling_load",
]

FIELDNAMES = [
    "id",
    "collect_time",
    "collect_time_iso",
    "device_id",
    *NUMERIC_COLUMNS,
]


def parse_float(value: str) -> str:
    """Return a normalized numeric string, or empty string for blanks."""
    value = value.strip()
    if not value:
        return ""
    number = float(value)
    return str(int(number)) if number.is_integer() else repr(number)


def read_rows(source: Path) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    """Read and normalize raw rows."""
    rows: list[dict[str, str]] = []
    parse_errors: list[dict[str, Any]] = []
    with source.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        for line_no, row in enumerate(reader, start=2):
            normalized = {
                key: value.strip() if isinstance(value, str) else ""
                for key, value in row.items()
            }
            try:
                collect_time = datetime.strptime(
                    normalized["collect_time"],
                    "%Y/%m/%d %H:%M",
                )
                normalized["collect_time_iso"] = collect_time.isoformat(sep=" ")
            except Exception as exc:  # noqa: BLE001
                parse_errors.append(
                    {
                        "line": line_no,
                        "column": "collect_time",
                        "value": normalized.get("collect_time", ""),
                        "error": str(exc),
                    }
                )
                normalized["collect_time_iso"] = ""

            for column in NUMERIC_COLUMNS:
                try:
                    normalized[column] = parse_float(normalized.get(column, ""))
                except Exception as exc:  # noqa: BLE001
                    parse_errors.append(
                        {
                            "line": line_no,
                            "column": column,
                            "value": normalized.get(column, ""),
                            "error": str(exc),
                        }
                    )
                    normalized[column] = ""
            rows.append({column: normalized.get(column, "") for column in FIELDNAMES})

    rows.sort(
        key=lambda row: (
            row.get("collect_time_iso", ""),
            row.get("device_id", ""),
            int(row["id"]) if row.get("id", "").isdigit() else 0,
        )
    )
    return rows, parse_errors


def numeric_stats(rows: list[dict[str, str]]) -> dict[str, dict[str, float | int | None]]:
    """Return count/min/max/mean for numeric columns."""
    stats: dict[str, dict[str, float | int | None]] = {}
    for column in NUMERIC_COLUMNS:
        values = [float(row[column]) for row in rows if row.get(column, "")]
        stats[column] = {
            "count": len(values),
            "min": min(values) if values else None,
            "max": max(values) if values else None,
            "mean": sum(values) / len(values) if values else None,
        }
    return stats


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    """Write CSV with UTF-8 BOM for Excel-friendly Chinese Windows use."""
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def device_summary(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Build per-device statistics."""
    devices = sorted({row["device_id"] for row in rows if row.get("device_id")})
    summary_rows: list[dict[str, Any]] = []
    for device in devices:
        device_rows = [row for row in rows if row.get("device_id") == device]
        times = [row["collect_time_iso"] for row in device_rows if row.get("collect_time_iso")]
        item: dict[str, Any] = {
            "device_id": device,
            "row_count": len(device_rows),
            "first_time": min(times) if times else "",
            "last_time": max(times) if times else "",
        }
        for column in NUMERIC_COLUMNS:
            values = [float(row[column]) for row in device_rows if row.get(column, "")]
            item[f"{column}_count"] = len(values)
            item[f"{column}_min"] = min(values) if values else ""
            item[f"{column}_max"] = max(values) if values else ""
            item[f"{column}_mean"] = sum(values) / len(values) if values else ""
        summary_rows.append(item)
    return summary_rows


def metadata(
    source: Path,
    raw_copy: Path,
    normalized_csv: Path,
    summary_csv: Path,
    rows: list[dict[str, str]],
    parse_errors: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build dataset metadata."""
    missing = {
        column: sum(1 for row in rows if row.get(column, "") == "")
        for column in FIELDNAMES
    }
    non_null = {column: len(rows) - missing[column] for column in FIELDNAMES}
    times = [row["collect_time_iso"] for row in rows if row.get("collect_time_iso")]
    timestamps = sorted(set(times))
    devices = sorted({row["device_id"] for row in rows if row.get("device_id")})
    timestamp_values = [
        datetime.fromisoformat(timestamp)
        for timestamp in timestamps
    ]
    interval_minutes = [
        (later - earlier).total_seconds() / 60.0
        for earlier, later in zip(timestamp_values[:-1], timestamp_values[1:])
    ]
    interval_counts: dict[str, int] = {}
    for interval in interval_minutes:
        key = str(int(interval)) if float(interval).is_integer() else f"{interval:.3f}"
        interval_counts[key] = interval_counts.get(key, 0) + 1
    device_type_counts: dict[str, int] = {}
    for device in devices:
        device_type = device.split("_", 1)[0]
        device_type_counts[device_type] = device_type_counts.get(device_type, 0) + 1
    return {
        "source_file": str(source),
        "raw_copy": str(raw_copy),
        "normalized_csv": str(normalized_csv),
        "device_summary_csv": str(summary_csv),
        "encoding": "utf-8-sig",
        "delimiter": ",",
        "row_count": len(rows),
        "column_count": len(FIELDNAMES),
        "columns": FIELDNAMES,
        "numeric_columns": NUMERIC_COLUMNS,
        "missing_count": missing,
        "non_null_count": non_null,
        "time_range": {
            "start": min(times) if times else None,
            "end": max(times) if times else None,
            "unique_timestamps": len(timestamps),
            "interval_minutes_count": interval_counts,
            "interval_minutes_min": min(interval_minutes) if interval_minutes else None,
            "interval_minutes_max": max(interval_minutes) if interval_minutes else None,
        },
        "device_count": len(devices),
        "devices": devices,
        "device_type_counts": device_type_counts,
        "numeric_stats": numeric_stats(rows),
        "parse_error_count": len(parse_errors),
        "parse_errors_sample": parse_errors[:20],
    }


def write_summary_markdown(path: Path, meta: dict[str, Any]) -> None:
    """Write a concise human-readable metadata summary."""
    lines = [
        "# 冷站设备运行数据元数据摘要",
        "",
        f"- 原始文件: `{meta['source_file']}`",
        f"- 原始副本: `{meta['raw_copy']}`",
        f"- 清洗数据: `{meta['normalized_csv']}`",
        f"- 设备汇总: `{meta['device_summary_csv']}`",
        "",
        f"- 行数: {meta['row_count']}",
        f"- 设备数: {meta['device_count']}",
        f"- 设备类型统计: {meta['device_type_counts']}",
        (
            "- 时间范围: "
            f"{meta['time_range']['start']} 至 {meta['time_range']['end']}"
        ),
        f"- 唯一时间戳数: {meta['time_range']['unique_timestamps']}",
        f"- 时间间隔分布 min: {meta['time_range']['interval_minutes_min']} min",
        f"- 时间间隔分布 max: {meta['time_range']['interval_minutes_max']} min",
        f"- 时间间隔计数: {meta['time_range']['interval_minutes_count']}",
        f"- 解析错误数: {meta['parse_error_count']}",
        "",
        "## 字段完整性",
        "",
    ]
    for column in FIELDNAMES:
        lines.append(
            f"- `{column}`: 非空 {meta['non_null_count'][column]}, "
            f"缺失 {meta['missing_count'][column]}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def process(source: Path, project_root: Path) -> dict[str, Any]:
    """Process one station device run CSV into project data files."""
    data_dir = project_root / "data"
    raw_dir = data_dir / "raw"
    processed_dir = data_dir / "processed"
    raw_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)

    raw_copy = raw_dir / source.name
    shutil.copy2(source, raw_copy)

    rows, parse_errors = read_rows(source)
    normalized_csv = processed_dir / "station_device_run_normalized.csv"
    write_csv(normalized_csv, rows, FIELDNAMES)

    summary_rows = device_summary(rows)
    summary_csv = processed_dir / "station_device_run_device_summary.csv"
    if summary_rows:
        write_csv(summary_csv, summary_rows, list(summary_rows[0].keys()))
    else:
        write_csv(summary_csv, [], ["device_id"])

    meta = metadata(
        source=source,
        raw_copy=raw_copy,
        normalized_csv=normalized_csv,
        summary_csv=summary_csv,
        rows=rows,
        parse_errors=parse_errors,
    )
    metadata_json = processed_dir / "station_device_run_metadata.json"
    metadata_json.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    meta["metadata_json"] = str(metadata_json)

    metadata_summary = processed_dir / "station_device_run_metadata_summary.md"
    write_summary_markdown(metadata_summary, meta)
    meta["metadata_summary_md"] = str(metadata_summary)
    return meta


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_csv", type=Path)
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    args = parser.parse_args()
    meta = process(args.source_csv, args.project_root)
    print(
        json.dumps(
            {
                "raw_copy": meta["raw_copy"],
                "normalized_csv": meta["normalized_csv"],
                "device_summary_csv": meta["device_summary_csv"],
                "metadata_json": meta["metadata_json"],
                "metadata_summary_md": meta["metadata_summary_md"],
                "row_count": meta["row_count"],
                "device_count": meta["device_count"],
                "time_range": meta["time_range"],
                "parse_error_count": meta["parse_error_count"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
