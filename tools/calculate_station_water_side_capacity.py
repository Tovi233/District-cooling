"""Calculate station cooling capacity with configured water-side or power-COP methods."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from district_cooling.operation import (
    calculate_water_side_capacity,
    load_capacity_config,
    load_station_workbook,
    summarize_water_side_capacity,
)


DEFAULT_INPUT = PROJECT_ROOT / "data" / "小梅沙.xlsx"
DEFAULT_CONFIG = PROJECT_ROOT / "src" / "district_cooling" / "operation" / "inputs" / "chiller_water_side_capacity_config.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "processed" / "water_side_capacity"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    data, _ = load_station_workbook(args.input)
    config = load_capacity_config(args.config)
    capacity = calculate_water_side_capacity(data, config)
    summary = summarize_water_side_capacity(capacity)

    timeseries_path = args.output_dir / "water_side_chiller_capacity_timeseries.csv"
    summary_path = args.output_dir / "water_side_chiller_capacity_summary.csv"
    report_path = args.output_dir / "water_side_chiller_capacity_report.md"
    xlsx_path = args.output_dir / "water_side_chiller_capacity.xlsx"

    capacity.to_csv(timeseries_path, index=False, encoding="utf-8-sig")
    summary.to_csv(summary_path, index=False, encoding="utf-8-sig")
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        capacity.to_excel(writer, sheet_name="水侧冷量时序", index=False)
        summary.to_excel(writer, sheet_name="水侧冷量汇总", index=False)
    report_path.write_text(_build_report(summary, config), encoding="utf-8")

    print(summary.to_string(index=False))
    print(f"Wrote outputs to {args.output_dir}")


def _build_report(summary: pd.DataFrame, config) -> str:
    lines = [
        "# 冷机制冷量混合计算",
        "",
        "## 计算方法",
        "",
        "CH_01 基载冷水机组功率暂认为不可靠，使用冷冻水侧温差和对应水泵流量估算制冷量。",
        "",
        "Q_water = rho * cp * V / 3600 * (T_chw_in - T_chw_out)",
        "",
        "其余可用冷机使用电机功率和 COP 估算制冷量。",
        "",
        "Q_power = P_motor * COP",
        "",
        "## 当前设备映射",
        "",
    ]
    for mapping in config.chiller_mappings:
        lines.append(
            f"- {mapping['chiller_id']} -> {mapping['pump_id']}, "
            f"方法 {mapping.get('capacity_method', 'water_side')}, "
            f"额定流量 {mapping['rated_flow_m3h']} m3/h, "
            f"使用={mapping.get('use', True)}"
        )
    lines.extend(["", "## 结果汇总", ""])
    lines.append("| 项目 | 平均 | 最小 | 最大 | P05 | P95 | 非零点数 |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for _, row in summary.iterrows():
        lines.append(
            f"| {row['item']} | {row['mean_kw']:.3f} | {row['min_kw']:.3f} | "
            f"{row['max_kw']:.3f} | {row['p05_kw']:.3f} | {row['p95_kw']:.3f} | "
            f"{int(row['nonzero_points'])} |"
        )
    ratio_row = summary[summary["item"] == "capacity_to_system_load_ratio"]
    if not ratio_row.empty:
        ratio_mean = float(ratio_row.iloc[0]["mean_kw"])
        lines.extend(
            [
                "",
                "## 注意",
                "",
                f"当前计算冷量与系统总冷量的平均比值为 {ratio_mean:.3f}。",
                "这说明用当前水泵额定流量直接代理冷冻水侧流量仍然偏粗。",
                "如果后续获得冷冻水泵、乙二醇泵或各冷机实际流量，应优先替换当前配置中的额定流量和流量估算方法。",
            ]
        )
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
