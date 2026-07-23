"""Identify cold-station operation modes from the final Xiaomeisha workbook."""

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

from district_cooling.operation import ModeRuleConfig, classify_operation_modes, load_station_workbook
from district_cooling.operation.mode_rules import daily_mode_summary, summarize_modes


DEFAULT_INPUT = PROJECT_ROOT / "data" / "小梅沙.xlsx"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "processed" / "operation_mode_identification"
DEFAULT_CONFIG = PROJECT_ROOT / "src" / "district_cooling" / "operation" / "inputs" / "station_operation_mode_config.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Final station workbook path.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT, help="Directory for generated results.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="Equipment-role and threshold config.")
    parser.add_argument("--clean", action="store_true", help="Delete the output directory before writing new results.")
    parser.add_argument("--design-capacity-kw", type=float, default=20113.0)
    parser.add_argument("--ice-delta-threshold", type=float, default=50.0)
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

    data, columns = load_station_workbook(args.input)
    config_values = _load_config_values(args.config)
    config_values["design_cooling_capacity_kw"] = args.design_capacity_kw
    config_values["ice_delta_threshold_per_step"] = args.ice_delta_threshold
    config = ModeRuleConfig(**config_values)
    features = classify_operation_modes(data, config)
    mode_summary = summarize_modes(features)
    daily_summary = daily_mode_summary(features)

    detail_path = args.output_dir / "station_operation_modes_timeseries.csv"
    summary_path = args.output_dir / "station_operation_modes_summary.csv"
    daily_path = args.output_dir / "station_operation_modes_daily.csv"
    criteria_path = args.output_dir / "station_operation_mode_criteria.csv"
    xlsx_path = args.output_dir / "station_operation_modes.xlsx"
    report_path = args.output_dir / "station_operation_modes_report.md"
    meta_path = args.output_dir / "station_operation_modes_metadata.json"

    features.to_csv(detail_path, index=False, encoding="utf-8-sig")
    mode_summary.to_csv(summary_path, index=False, encoding="utf-8-sig")
    daily_summary.to_csv(daily_path, index=False, encoding="utf-8-sig")
    criteria = _criteria_table(config)
    criteria.to_csv(criteria_path, index=False, encoding="utf-8-sig")

    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        features.to_excel(writer, sheet_name="逐时刻工况判定", index=False)
        mode_summary.to_excel(writer, sheet_name="工况汇总", index=False)
        daily_summary.to_excel(writer, sheet_name="每日工况", index=False)
        criteria.to_excel(writer, sheet_name="工况判据", index=False)

    meta = {
        "input": str(args.input),
        "time_start": str(features["collect_time_iso"].min()),
        "time_end": str(features["collect_time_iso"].max()),
        "time_points": int(len(features)),
        "device_parameter_points": int(len(columns)),
        "config": config.__dict__,
        "outputs": {
            "timeseries_csv": str(detail_path),
            "summary_csv": str(summary_path),
            "daily_csv": str(daily_path),
            "criteria_csv": str(criteria_path),
            "xlsx": str(xlsx_path),
            "report": str(report_path),
        },
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(_build_report(features, mode_summary, config), encoding="utf-8")

    print(f"Loaded {len(features)} time points from {args.input}")
    print(f"Wrote operation-mode results to {args.output_dir}")


def _build_report(features: pd.DataFrame, mode_summary: pd.DataFrame, config: ModeRuleConfig) -> str:
    start = features["collect_time_iso"].min()
    end = features["collect_time_iso"].max()
    lines = [
        "# 小梅沙冷站工况识别结果",
        "",
        "## 数据范围",
        "",
        f"- 时间范围: {start} 至 {end}",
        f"- 时间点数量: {len(features)}",
        f"- 设计制冷量: {config.design_cooling_capacity_kw:g} kW",
        f"- 蓄冰/释冰判定阈值: {config.ice_delta_threshold_per_step:g} 每步",
        f"- 机载/基载冷水机组: {', '.join(config.base_chiller_ids)}",
        f"- 双工况冷水机组: {', '.join(config.dual_mode_chiller_ids)}",
        f"- 暂不参与主工况判别的冷机测点: {', '.join(config.ignored_chiller_ids)}",
        "",
        "## 工况判据",
        "",
        _criteria_markdown(_criteria_table(config)),
        "",
        "## 工况汇总",
        "",
        "| 工况 | 点数 | 约持续时间(h) | 平均冷负荷(kW) | 平均负荷率 | 平均功率(kW) | 平均流量(m3/h) | 平均机载台数 | 平均双工况台数 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for _, row in mode_summary.iterrows():
        lines.append(
            f"| {row['operation_mode']} | {int(row['time_points'])} | "
            f"{row['duration_h']:.2f} | {row['mean_cooling_load_kw']:.2f} | "
            f"{row['mean_load_ratio']:.3f} | {row['mean_power_kw']:.2f} | "
            f"{row['mean_flow_m3h']:.2f} | {row['mean_base_chiller_on_count']:.2f} | "
            f"{row['mean_dual_chiller_on_count']:.2f} |"
        )
    lines.append("")
    return "\n".join(lines)


def _criteria_table(config: ModeRuleConfig) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "工况": "异常",
                "具体数值": "不属于下列任一正常工况",
                "备注": f"停机辅助阈值: cooling_load < {config.standby_cooling_load_kw:g} kW 且 base_chiller_on_count = 0 且 dual_chiller_on_count = 0；或 flow_m3h < {config.standby_flow_m3h:g}",
            },
            {
                "工况": "制冰",
                "具体数值": f"dual_chiller_on_count >= 1 且 dual_min_chw_out_temp_c < {config.ice_making_supply_temp_threshold_c:g} degC",
                "备注": f"第一优先级判据；只要双工况机组运行并产出零下工质，即判为制冰；双工况冷机编号: {', '.join(config.dual_mode_chiller_ids)}",
            },
            {
                "工况": "释冰",
                "具体数值": f"base_chiller_on_count = 0，dual_chiller_on_count = 0，ice_delta_per_step < -{config.ice_delta_threshold_per_step:g}",
                "备注": "不处于制冰时，若蓄冰量明显下降且无主冷机运行，则判为纯释冰",
            },
            {
                "工况": "释冰+基载",
                "具体数值": f"base_chiller_on_count >= 1，dual_chiller_on_count = 0，ice_delta_per_step < -{config.ice_delta_threshold_per_step:g}",
                "备注": "不处于制冰时，蓄冰量明显下降，且基载冷机运行、双工况冷机不运行",
            },
            {
                "工况": "释冰+基载+双工况",
                "具体数值": f"dual_chiller_on_count >= 1，base_chiller_on_count >= 1，ice_delta_per_step < -{config.ice_delta_threshold_per_step:g}",
                "备注": "不处于制冰时，蓄冰量明显下降，基载冷机和双工况冷机同时运行",
            },
            {
                "工况": "基载",
                "具体数值": "base_chiller_on_count >= 1，dual_chiller_on_count = 0，且不满足制冰/释冰判据",
                "备注": "冰量上升不再作为异常条件；这类变化可理解为蓄冰槽滞后或过渡状态",
            },
            {
                "工况": "基载+双工况",
                "具体数值": "base_chiller_on_count >= 1，dual_chiller_on_count >= 1，且不满足制冰/释冰判据",
                "备注": "双工况机组运行但未产出零下工质时，按机械制冷而非制冰处理",
            },
        ]
    )


def _criteria_markdown(criteria: pd.DataFrame) -> str:
    lines = ["| 工况 | 具体判据 | 备注 |", "|---|---|---|"]
    for _, row in criteria.iterrows():
        lines.append(f"| {row['工况']} | {row['具体数值']} | {row['备注']} |")
    return "\n".join(lines)


def _load_config_values(path: Path) -> dict:
    values = json.loads(path.read_text(encoding="utf-8"))
    for key in ("base_chiller_ids", "dual_mode_chiller_ids", "ignored_chiller_ids"):
        if key in values:
            values[key] = tuple(values[key])
    allowed = set(ModeRuleConfig.__dataclass_fields__)
    return {key: value for key, value in values.items() if key in allowed}


if __name__ == "__main__":
    main()
