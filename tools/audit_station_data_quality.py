"""Audit possible quality issues in the final Xiaomeisha station workbook."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from district_cooling.operation import load_station_workbook


DEFAULT_INPUT = PROJECT_ROOT / "data" / "小梅沙.xlsx"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "processed" / "station_data_quality_audit"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    data, columns = load_station_workbook(args.input)

    chiller_summary = _chiller_summary(data)
    consistency_issues = _consistency_issues(data)
    frequency_summary = _frequency_summary(data)
    system_summary = _system_summary(data)
    suspicious_columns = _suspicious_columns(data, columns)

    chiller_summary.to_csv(args.output_dir / "chiller_quality_summary.csv", index=False, encoding="utf-8-sig")
    consistency_issues.to_csv(args.output_dir / "device_consistency_issues.csv", index=False, encoding="utf-8-sig")
    frequency_summary.to_csv(args.output_dir / "frequency_quality_summary.csv", index=False, encoding="utf-8-sig")
    system_summary.to_csv(args.output_dir / "system_balance_summary.csv", index=False, encoding="utf-8-sig")
    suspicious_columns.to_csv(args.output_dir / "suspicious_columns.csv", index=False, encoding="utf-8-sig")

    report = _build_report(data, chiller_summary, consistency_issues, frequency_summary, system_summary, suspicious_columns)
    report_path = args.output_dir / "station_data_quality_audit_report.md"
    report_path.write_text(report, encoding="utf-8")
    print(report)
    print(f"\nWrote audit files to {args.output_dir}")


def _chiller_summary(data: pd.DataFrame) -> pd.DataFrame:
    records = []
    for dev in _devices(data, "CH_"):
        status = _num(data, f"{dev}__status")
        power = _num(data, f"{dev}__power_kw")
        tin = _num(data, f"{dev}__chw_in_temp")
        tout = _num(data, f"{dev}__chw_out_temp")
        delta_t = tin - tout
        on = status.gt(0.5)
        normal_power_like = power.ge(20)
        records.append(
            {
                "device": dev,
                "status_on_rate": on.mean(),
                "power_min_kw": power.min(),
                "power_max_kw": power.max(),
                "power_mean_kw": power.mean(),
                "power_mean_when_status_on_kw": power[on].mean(),
                "power_max_when_status_on_kw": power[on].max(),
                "chw_out_min_c": tout.min(),
                "chw_out_mean_c": tout.mean(),
                "chw_delta_t_mean_c": delta_t.mean(),
                "chw_delta_t_max_c": delta_t.max(),
                "status_on_but_power_below_20_count": int((on & power.lt(20)).sum()),
                "status_off_but_power_above_20_count": int((~on & power.gt(20)).sum()),
                "power_looks_like_main_chiller_rate": normal_power_like.mean(),
                "power_x10_mean_when_on_kw": power[on].mean() * 10,
                "power_x100_mean_when_on_kw": power[on].mean() * 100,
            }
        )
    return pd.DataFrame(records)


def _consistency_issues(data: pd.DataFrame) -> pd.DataFrame:
    records = []
    for dev in _devices(data, ""):
        status_col = f"{dev}__status"
        power_col = f"{dev}__power_kw"
        freq_col = f"{dev}__freq_hz"
        if status_col in data and power_col in data:
            status = _num(data, status_col)
            power = _num(data, power_col)
            _add_issue_rows(records, data, dev, "status=1但功率很低", status.gt(0.5) & power.lt(20), power_col)
            _add_issue_rows(records, data, dev, "status=0但功率较高", status.le(0.5) & power.gt(20), power_col)
        if freq_col in data and power_col in data:
            freq = _num(data, freq_col)
            power = _num(data, power_col)
            _add_issue_rows(records, data, dev, "频率>5Hz但功率接近0", freq.gt(5) & power.lt(1), freq_col)
            _add_issue_rows(records, data, dev, "频率=0但功率较高", freq.eq(0) & power.gt(5), power_col)
    return pd.DataFrame(records)


def _frequency_summary(data: pd.DataFrame) -> pd.DataFrame:
    records = []
    for col in [c for c in data.columns if c.endswith("__freq_hz")]:
        series = _num(data, col)
        valid = series.dropna()
        records.append(
            {
                "device": col.split("__", 1)[0],
                "parameter": "freq_hz",
                "count": int(valid.count()),
                "min": valid.min(),
                "max": valid.max(),
                "mean": valid.mean(),
                "negative_count": int(valid.lt(0).sum()),
                "constant_value": valid.nunique() == 1,
                "unique_count": int(valid.nunique()),
            }
        )
    return pd.DataFrame(records)


def _system_summary(data: pd.DataFrame) -> pd.DataFrame:
    flow = _num(data, "SYS_TOTAL__flow_m3h")
    cooling_load = _num(data, "SYS_TOTAL__cooling_load")
    total_power = _num(data, "SYS_TOTAL__power_kw")
    mass_flow = flow * 1000.0 / 3600.0
    implied_delta_t = cooling_load / (mass_flow * 4.186)
    cop_like = cooling_load / total_power.replace(0, pd.NA)
    return pd.DataFrame(
        [
            {
                "metric": "system_implied_delta_t_c",
                "min": implied_delta_t.min(),
                "p05": implied_delta_t.quantile(0.05),
                "mean": implied_delta_t.mean(),
                "p95": implied_delta_t.quantile(0.95),
                "max": implied_delta_t.max(),
                "suspicious_count_lt_1_or_gt_8": int((implied_delta_t.lt(1) | implied_delta_t.gt(8)).sum()),
            },
            {
                "metric": "system_cop_like_cooling_load_over_power",
                "min": cop_like.min(),
                "p05": cop_like.quantile(0.05),
                "mean": cop_like.mean(),
                "p95": cop_like.quantile(0.95),
                "max": cop_like.max(),
                "suspicious_count_lt_1_or_gt_10": int((cop_like.lt(1) | cop_like.gt(10)).sum()),
            },
        ]
    )


def _suspicious_columns(data: pd.DataFrame, columns: list) -> pd.DataFrame:
    records = []
    for meta in columns:
        col = meta.column
        series = _num(data, col)
        valid = series.dropna()
        if valid.empty:
            records.append({"column": col, "reason": "全空", "detail": ""})
            continue
        if meta.parameter == "power_kw" and meta.device.startswith("CH_") and valid.max() < 100:
            records.append({"column": col, "reason": "冷机功率量级过低", "detail": f"max={valid.max():.3f} kW"})
        if meta.parameter == "freq_hz" and valid.nunique() == 1:
            records.append({"column": col, "reason": "频率全程恒定", "detail": f"value={valid.iloc[0]:.3f} Hz"})
        if meta.parameter == "freq_hz" and (valid < 0).any():
            records.append({"column": col, "reason": "频率存在负值", "detail": f"negative_count={(valid < 0).sum()}"})
        if meta.parameter.endswith("temp") and (valid.lt(-10).any() or valid.gt(60).any()):
            records.append({"column": col, "reason": "温度超常见暖通范围", "detail": f"min={valid.min():.3f}, max={valid.max():.3f}"})
    return pd.DataFrame(records)


def _build_report(
    data: pd.DataFrame,
    chiller_summary: pd.DataFrame,
    consistency_issues: pd.DataFrame,
    frequency_summary: pd.DataFrame,
    system_summary: pd.DataFrame,
    suspicious_columns: pd.DataFrame,
) -> str:
    lines = [
        "# 小梅沙冷站数据质量专项检查",
        "",
        "## 结论优先",
        "",
    ]
    for _, row in suspicious_columns.iterrows():
        lines.append(f"- {row['column']}: {row['reason']} ({row['detail']})")
    if suspicious_columns.empty:
        lines.append("- 未发现明显量级或格式异常列。")

    lines.extend(["", "## 冷机功率与状态检查", "", _table(chiller_summary)])
    lines.extend(["", "## 系统总量一致性检查", "", _table(system_summary)])
    lines.extend(["", "## 频率测点检查", "", _table(frequency_summary)])
    issue_counts = consistency_issues.groupby(["device", "issue"]).size().reset_index(name="count") if not consistency_issues.empty else pd.DataFrame()
    lines.extend(["", "## 状态-功率/频率-功率矛盾统计", "", _table(issue_counts)])
    lines.extend(
        [
            "",
            "## 对 CH_01 的判断",
            "",
            "CH_01 的运行状态和冷冻水出水温度像是在参与常规供冷，但 power_kw 最大值只有约 70 kW。",
            "若该列整体乘以 10，则运行时平均功率约为几百 kW，量级会更接近一台常规冷水机组的部分负荷功率。",
            "因此 CH_01__power_kw 是当前最值得向数据提供方核对的列之一。",
        ]
    )
    return "\n".join(lines)


def _devices(data: pd.DataFrame, prefix: str) -> list[str]:
    devices = sorted({col.split("__", 1)[0] for col in data.columns if "__" in col and col.startswith(prefix)})
    return devices


def _num(data: pd.DataFrame, col: str) -> pd.Series:
    if col not in data:
        return pd.Series(pd.NA, index=data.index, dtype="Float64")
    return pd.to_numeric(data[col], errors="coerce")


def _add_issue_rows(records: list[dict], data: pd.DataFrame, device: str, issue: str, mask: pd.Series, value_col: str) -> None:
    bad = data.loc[mask.fillna(False), ["collect_time_iso", value_col]].head(20)
    for _, row in bad.iterrows():
        records.append(
            {
                "device": device,
                "issue": issue,
                "time": row["collect_time_iso"],
                "value_column": value_col,
                "value": row[value_col],
            }
        )


def _table(df: pd.DataFrame) -> str:
    if df.empty:
        return "无。"
    shown = df.copy()
    for col in shown.columns:
        if pd.api.types.is_float_dtype(shown[col]):
            shown[col] = shown[col].map(lambda value: "" if pd.isna(value) else f"{value:.3f}")
    headers = [str(col) for col in shown.columns]
    rows = []
    rows.append("| " + " | ".join(headers) + " |")
    rows.append("| " + " | ".join("---" for _ in headers) + " |")
    for _, row in shown.iterrows():
        values = ["" if pd.isna(row[col]) else str(row[col]) for col in shown.columns]
        rows.append("| " + " | ".join(values) + " |")
    return "\n".join(rows)


if __name__ == "__main__":
    main()
