from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
from PIL import Image, ImageDraw, ImageFont


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INPUT_DIR = PROJECT_ROOT / "data" / "processed" / "station_flexibility_potential"
OUTPUT_PATH = INPUT_DIR / "station_flexibility_visual_summary_clean.png"
SUMMARY_TEXT_PATH = INPUT_DIR / "station_flexibility_summary_clean.md"

MODE_MAP = {
    "�Ʊ�": "制冰",
    "����": "基载",
    "����+˫����": "基载+双工况",
    "�ͱ�+����": "释冰+基载",
    "�ͱ�+����+˫����": "释冰+基载+双工况",
    "�쳣": "异常",
}

LEVEL_MAP = {
    "����Ӧ": "可响应",
    "������Ӧ": "有限响应",
    "谨慎响应": "有限响应",
    "��������Ӧ": "不建议响应",
}

LEVEL_COLORS = {
    "可响应": "#2E7D32",
    "有限响应": "#F2A900",
    "不建议响应": "#9E9E9E",
}

MODE_ORDER = ["制冰", "基载", "基载+双工况", "释冰+基载", "释冰+基载+双工况", "异常"]
LEVEL_ORDER = ["可响应", "有限响应", "不建议响应"]

W, H = 2600, 1650


def main() -> None:
    ts = pd.read_csv(INPUT_DIR / "station_flexibility_timeseries.csv", encoding="utf-8-sig")
    ts["collect_time_iso"] = pd.to_datetime(ts["collect_time_iso"])
    ts["operation_mode_cn"] = ts["operation_mode"].map(MODE_MAP).fillna(ts["operation_mode"])
    ts["response_level_cn"] = ts["response_level"].map(LEVEL_MAP).fillna(ts["response_level"])

    image = Image.new("RGB", (W, H), "white")
    draw = ImageDraw.Draw(image)
    fonts = {
        "title": _font(54, bold=True),
        "h2": _font(36, bold=True),
        "normal": _font(28),
        "small": _font(23),
        "tiny": _font(19),
    }

    _center_text(draw, "冷站侧可调潜力量化结果总览", W // 2, 48, fonts["title"], "#111111")
    _draw_time_series(draw, ts, (90, 150, 1660, 620), fonts)
    _draw_metrics(draw, ts, (1780, 160, 2470, 700), fonts)
    _draw_mode_bars(draw, ts, (90, 760, 1150, 1450), fonts)
    _draw_level_pie(draw, ts, (1330, 760, 1840, 1265), fonts)
    _draw_mode_level_stack(draw, ts, (1340, 1295, 2470, 1540), fonts)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    image.save(OUTPUT_PATH, quality=95)
    SUMMARY_TEXT_PATH.write_text(_build_summary_text(ts), encoding="utf-8")
    print(OUTPUT_PATH)
    print(SUMMARY_TEXT_PATH)


def _draw_time_series(draw: ImageDraw.ImageDraw, df: pd.DataFrame, box: tuple[int, int, int, int], fonts: dict) -> None:
    x0, y0, x1, y1 = box
    _center_text(draw, "当前总功率与分来源可削减功率", (x0 + x1) // 2, y0 - 42, fonts["h2"], "#111111")
    chart = (x0 + 120, y0 + 45, x1 - 40, y1 - 75)
    _axes(draw, chart)
    y_max = max(float(df["power_kw"].max()), float(df["reducible_power_kw"].max()), 1.0) * 1.08
    _stacked_response_bars(draw, df, chart, 0, y_max)
    p1 = _series_points(df["power_kw"], chart, 0, y_max)
    draw.line(p1, fill="#1F77B4", width=5)
    _y_ticks(draw, chart, 0, y_max, fonts["tiny"], "功率 (kW)")
    _time_ticks(draw, df, chart, fonts["tiny"])
    _legend(
        draw,
        chart[0] + 28,
        chart[1] + 18,
        [
            ("当前总功率", "#1F77B4"),
            ("停止/降低制冰", "#FF7F0E"),
            ("蓄冰替代冷机", "#D62728"),
            ("供水温度上调", "#0891B2"),
        ],
        fonts["small"],
    )


def _stacked_response_bars(
    draw: ImageDraw.ImageDraw,
    df: pd.DataFrame,
    chart: tuple[int, int, int, int],
    v_min: float,
    v_max: float,
) -> None:
    x0, y0, x1, y1 = chart
    n = len(df)
    plot_w = x1 - x0
    bar_w = max(1, int(plot_w / max(n, 1) * 0.86))
    stop_values = pd.to_numeric(df["stop_ice_making_power_kw"], errors="coerce").fillna(0).to_numpy()
    shift_values = pd.to_numeric(df["load_shift_power_kw"], errors="coerce").fillna(0).to_numpy()
    supply_values = (
        pd.to_numeric(df["supply_temp_reduction_power_kw"], errors="coerce").fillna(0).to_numpy()
        if "supply_temp_reduction_power_kw" in df
        else [0.0] * len(df)
    )
    for i, (stop_kw, shift_kw, supply_kw) in enumerate(zip(stop_values, shift_values, supply_values)):
        x = x0 + int(i * plot_w / max(n - 1, 1))
        x_left = max(x0, x - bar_w // 2)
        x_right = min(x1, x_left + bar_w)
        if stop_kw <= 0 and shift_kw <= 0 and supply_kw <= 0:
            continue
        base_y = y1
        if stop_kw > 0:
            top_y = _value_y(stop_kw, v_min, v_max, y0, y1)
            draw.rectangle((x_left, top_y, x_right, base_y), fill="#FF7F0E")
            base_y = top_y
        if shift_kw > 0:
            top_y = _value_y(stop_kw + shift_kw, v_min, v_max, y0, y1)
            draw.rectangle((x_left, top_y, x_right, base_y), fill="#D62728")
            base_y = top_y
        if supply_kw > 0:
            top_y = _value_y(stop_kw + shift_kw + supply_kw, v_min, v_max, y0, y1)
            draw.rectangle((x_left, top_y, x_right, base_y), fill="#0891B2")


def _draw_metrics(draw: ImageDraw.ImageDraw, df: pd.DataFrame, box: tuple[int, int, int, int], fonts: dict) -> None:
    x0, y0, x1, y1 = box
    draw.rounded_rectangle(box, radius=20, fill="#F8FAFC", outline="#D5DEE8", width=2)
    draw.text((x0 + 28, y0 + 24), "关键指标", font=fonts["h2"], fill="#111111")
    metrics = [
        ("数据点数", len(df), "点"),
        ("平均冷负荷", df["cooling_load_kw"].mean(), "kW"),
        ("平均总功率", df["power_kw"].mean(), "kW"),
        ("平均可削减功率", df["reducible_power_kw"].mean(), "kW"),
        ("最大可削减功率", df["reducible_power_kw"].max(), "kW"),
        ("供水温度上调削减", df.get("supply_temp_reduction_power_kw", pd.Series([0])).mean(), "kW"),
        ("平均响应时长", df["response_duration_h"].mean(), "h"),
        ("平均可转移冷量", df["transferable_cooling_energy_kwh"].mean(), "kWh"),
        ("平均反弹功率", df["rebound_power_kw"].mean(), "kW"),
    ]
    y = y0 + 92
    for name, value, unit in metrics:
        value_str = f"{value:,.0f} {unit}" if unit in {"点", "kW", "kWh"} else f"{value:.2f} {unit}"
        draw.text((x0 + 32, y), name, font=fonts["small"], fill="#334155")
        tw = draw.textbbox((0, 0), value_str, font=fonts["small"])[2]
        draw.text((x1 - 32 - tw, y), value_str, font=fonts["small"], fill="#111111")
        y += 58


def _draw_mode_bars(draw: ImageDraw.ImageDraw, df: pd.DataFrame, box: tuple[int, int, int, int], fonts: dict) -> None:
    x0, y0, x1, y1 = box
    _center_text(draw, "分工况平均可削减功率", (x0 + x1) // 2, y0 - 42, fonts["h2"], "#111111")
    chart = (x0 + 330, y0 + 30, x1 - 95, y1 - 65)
    _axes(draw, chart)
    summary = (
        df.groupby("operation_mode_cn")
        .agg(mean_kw=("reducible_power_kw", "mean"), max_kw=("reducible_power_kw", "max"), points=("collect_time_iso", "count"))
        .reindex(MODE_ORDER)
        .dropna()
        .reset_index()
    )
    max_v = max(float(summary["mean_kw"].max()), 1.0) * 1.15
    bar_h = 48
    gap = 34
    for i, row in summary.iterrows():
        y = chart[1] + i * (bar_h + gap)
        mode = str(row["operation_mode_cn"])
        value = float(row["mean_kw"])
        width = int(value / max_v * (chart[2] - chart[0]))
        draw.text((chart[0] - 18, y + bar_h // 2), mode, font=fonts["small"], fill="#222222", anchor="rm")
        draw.rectangle((chart[0], y, chart[0] + width, y + bar_h), fill="#D62728")
        draw.text((chart[0] + width + 12, y + bar_h // 2), f"{value:.0f}", font=fonts["small"], fill="#222222", anchor="lm")
    _center_text(draw, "平均可削减功率 (kW)", (chart[0] + chart[2]) // 2, chart[3] + 34, fonts["tiny"], "#333333")


def _draw_level_pie(draw: ImageDraw.ImageDraw, df: pd.DataFrame, box: tuple[int, int, int, int], fonts: dict) -> None:
    x0, y0, x1, y1 = box
    _center_text(draw, "响应等级占比", (x0 + x1) // 2, y0 - 42, fonts["h2"], "#111111")
    counts = df["response_level_cn"].value_counts().reindex(LEVEL_ORDER, fill_value=0)
    total = max(int(counts.sum()), 1)
    cx, cy, r = (x0 + x1) // 2 - 55, (y0 + y1) // 2, 185
    start = -90
    for level in LEVEL_ORDER:
        count = int(counts[level])
        end = start + 360 * count / total
        draw.pieslice((cx - r, cy - r, cx + r, cy + r), start, end, fill=LEVEL_COLORS[level])
        start = end
    lx, ly = cx + 245, cy - 112
    for level in LEVEL_ORDER:
        count = int(counts[level])
        pct = count / total * 100
        draw.rectangle((lx, ly, lx + 32, ly + 24), fill=LEVEL_COLORS[level])
        draw.text((lx + 46, ly - 5), f"{level}: {count}点", font=fonts["small"], fill="#222222")
        draw.text((lx + 46, ly + 27), f"{pct:.1f}%", font=fonts["tiny"], fill="#555555")
        ly += 88


def _draw_mode_level_stack(draw: ImageDraw.ImageDraw, df: pd.DataFrame, box: tuple[int, int, int, int], fonts: dict) -> None:
    x0, y0, x1, y1 = box
    _center_text(draw, "各响应等级持续时间", (x0 + x1) // 2, y0 - 38, fonts["h2"], "#111111")
    pivot = (
        df.pivot_table(index="response_level_cn", values="collect_time_iso", aggfunc="count")
        .reindex(LEVEL_ORDER)
        .fillna(0)
    )
    total_h = len(df) * 0.25
    x = x0 + 40
    y = y0 + 56
    max_w = x1 - x0 - 170
    for level in LEVEL_ORDER:
        h = float(pivot.loc[level, "collect_time_iso"]) * 0.25
        w = int(h / total_h * max_w)
        draw.rectangle((x, y, x + w, y + 44), fill=LEVEL_COLORS[level])
        draw.text((x + w + 14, y + 22), f"{level} {h:.2f} h", font=fonts["small"], fill="#222222", anchor="lm")
        y += 64


def _build_summary_text(df: pd.DataFrame) -> str:
    total_h = len(df) * 0.25
    counts = df["response_level_cn"].value_counts().reindex(LEVEL_ORDER, fill_value=0)
    summary = (
        df.groupby("operation_mode_cn")
        .agg(duration_h=("collect_time_iso", lambda s: len(s) * 0.25), mean_kw=("reducible_power_kw", "mean"), max_kw=("reducible_power_kw", "max"))
        .reindex(MODE_ORDER)
        .dropna()
        .reset_index()
    )
    lines = [
        "# 冷站侧可调潜力量化结果总结",
        "",
        f"- 本次共计算 {len(df)} 个15分钟时刻，折合 {total_h:.2f} h。",
        f"- 平均冷负荷为 {df['cooling_load_kw'].mean():.1f} kW，平均总功率为 {df['power_kw'].mean():.1f} kW。",
        f"- 平均可削减功率为 {df['reducible_power_kw'].mean():.1f} kW，最大可削减功率为 {df['reducible_power_kw'].max():.1f} kW。",
        f"- 供水温度上调带来的平均可削减功率为 {df.get('supply_temp_reduction_power_kw', pd.Series([0])).mean():.1f} kW。",
        f"- 平均可响应时长为 {df['response_duration_h'].mean():.2f} h，平均可转移冷量为 {df['transferable_cooling_energy_kwh'].mean():.1f} kWh。",
        f"- 平均反弹功率为 {df['rebound_power_kw'].mean():.1f} kW。",
        "",
        "## 响应等级",
    ]
    for level in LEVEL_ORDER:
        count = int(counts[level])
        lines.append(f"- {level}: {count} 点，{count * 0.25:.2f} h，占比 {count / len(df) * 100:.1f}%。")
    lines.extend(["", "## 分工况平均可削减功率"])
    for _, row in summary.iterrows():
        lines.append(f"- {row['operation_mode_cn']}: 平均 {row['mean_kw']:.1f} kW，最大 {row['max_kw']:.1f} kW，持续 {row['duration_h']:.2f} h。")
    lines.append("")
    return "\n".join(lines)


def _axes(draw: ImageDraw.ImageDraw, chart: tuple[int, int, int, int]) -> None:
    x0, y0, x1, y1 = chart
    draw.line((x0, y1, x1, y1), fill="#222222", width=3)
    draw.line((x0, y0, x0, y1), fill="#222222", width=3)
    for i in range(1, 5):
        y = y1 - i * (y1 - y0) / 5
        draw.line((x0, y, x1, y), fill="#E5E7EB", width=1)


def _series_points(values: pd.Series, chart: tuple[int, int, int, int], v_min: float, v_max: float) -> list[tuple[int, int]]:
    x0, y0, x1, y1 = chart
    out = []
    n = len(values)
    for i, value in enumerate(values):
        x = x0 + int(i * (x1 - x0) / max(n - 1, 1))
        y = _value_y(float(value), v_min, v_max, y0, y1)
        out.append((x, y))
    return out


def _value_y(value: float, v_min: float, v_max: float, y0: int, y1: int) -> int:
    if v_max == v_min:
        return int((y0 + y1) / 2)
    return y1 - int((float(value) - v_min) / (v_max - v_min) * (y1 - y0))


def _y_ticks(draw: ImageDraw.ImageDraw, chart: tuple[int, int, int, int], v_min: float, v_max: float, font: ImageFont.ImageFont, label: str) -> None:
    x0, y0, _, y1 = chart
    for i in range(5):
        value = v_min + (v_max - v_min) * i / 4
        y = y1 - int((value - v_min) / (v_max - v_min) * (y1 - y0))
        draw.line((x0 - 8, y, x0, y), fill="#222222", width=2)
        draw.text((x0 - 14, y), f"{value:.0f}", font=font, fill="#333333", anchor="rm")
    draw.text((x0 - 92, y0 - 26), label, font=font, fill="#333333")


def _time_ticks(draw: ImageDraw.ImageDraw, df: pd.DataFrame, chart: tuple[int, int, int, int], font: ImageFont.ImageFont) -> None:
    x0, _, x1, y1 = chart
    dates = df["collect_time_iso"].dt.date.astype(str)
    for date in sorted(dates.unique()):
        idx = int(dates[dates == date].index[0])
        x = x0 + int(idx * (x1 - x0) / max(len(df) - 1, 1))
        draw.line((x, y1, x, y1 + 10), fill="#222222", width=2)
        draw.text((x, y1 + 16), date[5:], font=font, fill="#333333", anchor="ma")
    _center_text(draw, "时间", (x0 + x1) // 2, y1 + 58, font, "#333333")


def _legend(draw: ImageDraw.ImageDraw, x: int, y: int, items: list[tuple[str, str]], font: ImageFont.ImageFont) -> None:
    for label, color in items:
        draw.line((x, y + 12, x + 48, y + 12), fill=color, width=5)
        draw.text((x + 62, y), label, font=font, fill="#222222")
        x += 230


def _center_text(draw: ImageDraw.ImageDraw, text: str, x: int, y: int, font: ImageFont.ImageFont, fill: str) -> None:
    bbox = draw.textbbox((0, 0), text, font=font)
    draw.text((x - (bbox[2] - bbox[0]) / 2, y), text, font=font, fill=fill)


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        Path("C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
    ]
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


if __name__ == "__main__":
    main()
