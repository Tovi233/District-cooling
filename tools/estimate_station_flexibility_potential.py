"""Estimate first-stage district-cooling flexibility from cold-station data only."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from district_cooling.operation import (  # noqa: E402
    estimate_station_flexibility,
    load_flexibility_config,
    summarize_flexibility,
)


DEFAULT_INPUT = PROJECT_ROOT / "data" / "processed" / "operation_mode_identification" / "station_operation_modes_timeseries.csv"
DEFAULT_CONFIG = PROJECT_ROOT / "src" / "district_cooling" / "operation" / "inputs" / "station_flexibility_config.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "processed" / "station_flexibility_potential"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Operation-mode time-series CSV.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="Flexibility assumption JSON.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT, help="Output directory.")
    parser.add_argument("--clean", action="store_true", help="Delete the output directory before writing new results.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.clean and args.output_dir.exists():
        resolved_output = args.output_dir.resolve()
        resolved_project = PROJECT_ROOT.resolve()
        if resolved_project not in resolved_output.parents:
            raise RuntimeError(f"Refusing to clean output outside project: {resolved_output}")
        shutil.rmtree(resolved_output)

    args.output_dir.mkdir(parents=True, exist_ok=True)

    operation_modes = pd.read_csv(args.input, encoding="utf-8-sig")
    config = load_flexibility_config(args.config)
    flexibility = estimate_station_flexibility(operation_modes, config)
    summary = summarize_flexibility(flexibility)
    overall = _overall_summary(flexibility)

    timeseries_path = args.output_dir / "station_flexibility_timeseries.csv"
    summary_path = args.output_dir / "station_flexibility_summary.csv"
    overall_path = args.output_dir / "station_flexibility_overall.csv"
    report_path = args.output_dir / "station_flexibility_report.md"
    xlsx_path = args.output_dir / "station_flexibility.xlsx"
    meta_path = args.output_dir / "station_flexibility_metadata.json"

    flexibility.to_csv(timeseries_path, index=False, encoding="utf-8-sig")
    summary.to_csv(summary_path, index=False, encoding="utf-8-sig")
    overall.to_csv(overall_path, index=False, encoding="utf-8-sig")

    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        flexibility.to_excel(writer, sheet_name="逐时可调潜力", index=False)
        summary.to_excel(writer, sheet_name="工况汇总", index=False)
        overall.to_excel(writer, sheet_name="总体指标", index=False)

    meta = {
        "input": str(args.input),
        "config": config.__dict__,
        "time_start": str(pd.to_datetime(flexibility["collect_time_iso"]).min()),
        "time_end": str(pd.to_datetime(flexibility["collect_time_iso"]).max()),
        "time_points": int(len(flexibility)),
        "outputs": {
            "timeseries_csv": str(timeseries_path),
            "summary_csv": str(summary_path),
            "overall_csv": str(overall_path),
            "xlsx": str(xlsx_path),
            "report": str(report_path),
        },
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(_build_report(summary, overall, config.__dict__), encoding="utf-8")

    print(f"Loaded {len(flexibility)} time points from {args.input}")
    print(f"Wrote flexibility results to {args.output_dir}")


def _overall_summary(flexibility: pd.DataFrame) -> pd.DataFrame:
    response_counts = flexibility["response_level"].value_counts()
    return pd.DataFrame(
        [
            {"指标": "平均当前冷负荷", "数值": flexibility["cooling_load_kw"].mean(), "单位": "kW"},
            {"指标": "平均当前总功率", "数值": flexibility["power_kw"].mean(), "单位": "kW"},
            {"指标": "平均系统综合COP", "数值": flexibility["station_cop"].mean(), "单位": "-"},
            {"指标": "平均可削减功率", "数值": flexibility["reducible_power_kw"].mean(), "单位": "kW"},
            {"指标": "最大可削减功率", "数值": flexibility["reducible_power_kw"].max(), "单位": "kW"},
            {"指标": "平均供水温度上调可削减功率", "数值": flexibility["supply_temp_reduction_power_kw"].mean(), "单位": "kW"},
            {"指标": "平均供水过冷温差", "数值": flexibility["overcooling_delta_temp_c"].mean(), "单位": "degC"},
            {"指标": "平均可响应时长", "数值": flexibility["response_duration_h"].mean(), "单位": "h"},
            {"指标": "平均蓄冰可释冷支撑时长", "数值": flexibility["ice_supported_duration_h"].mean(), "单位": "h"},
            {"指标": "平均可转移冷量", "数值": flexibility["transferable_cooling_energy_kwh"].mean(), "单位": "kWh"},
            {"指标": "平均反弹功率", "数值": flexibility["rebound_power_kw"].mean(), "单位": "kW"},
            {"指标": "可响应点数", "数值": float(response_counts.get("可响应", 0)), "单位": "点"},
            {"指标": "有限响应点数", "数值": float(response_counts.get("有限响应", 0)), "单位": "点"},
            {"指标": "不建议响应点数", "数值": float(response_counts.get("不建议响应", 0)), "单位": "点"},
        ]
    )


def _build_report(summary: pd.DataFrame, overall: pd.DataFrame, config_values: dict) -> str:
    lines = [
        "# 冷站侧可调潜力估算结果",
        "",
        "## 计算口径",
        "",
        "- 本结果属于第一阶段快速估算，仅使用冷站侧数据，暂不耦合建筑热惯性和管网动态。",
        "- 制冰阶段根据双工况机组低温出水和制冰能力估算停止制冰可削减功率。",
        "- 机械制冷阶段根据可用释冰功率替代正在运行的冷机冷量，并按被替代冷机 COP 折算削减电功率。",
        "- 当基载和双工况同时运行时，释冰优先替代双工况冷量，再替代基载冷量。",
        "- 当用户侧总供水温度低于合同供水温度时，将过冷冷量换算为可上调供水温度带来的可削减电功率。",
        "",
        "## 关键假设",
        "",
    ]
    for key, value in config_values.items():
        lines.append(f"- {key}: {value}")

    lines.extend(["", "## 总体指标", "", "| 指标 | 数值 | 单位 |", "|---|---:|---|"])
    for _, row in overall.iterrows():
        lines.append(f"| {row['指标']} | {row['数值']:.3f} | {row['单位']} |")

    lines.extend(
        [
            "",
            "## 分工况结果",
            "",
            "| 工况 | 响应等级 | 点数 | 持续时间(h) | 平均可削减功率(kW) | 最大可削减功率(kW) | 平均可响应时长(h) | 平均反弹功率(kW) |",
            "|---|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for _, row in summary.iterrows():
        lines.append(
            f"| {row['operation_mode']} | {row['response_level']} | {int(row['time_points'])} | "
            f"{row['duration_h']:.2f} | {row['mean_reducible_power_kw']:.2f} | "
            f"{row['max_reducible_power_kw']:.2f} | {row['mean_response_duration_h']:.2f} | "
            f"{row['mean_rebound_power_kw']:.2f} |"
        )
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
