"""Create visual summaries for station operation-mode identification results."""

from __future__ import annotations

import argparse
import html
from pathlib import Path

import pandas as pd
from PIL import Image, ImageDraw, ImageFont


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_DIR = PROJECT_ROOT / "data" / "processed" / "operation_mode_identification"
RT_TO_KW = 3.517

MODE_COLORS = {
    "无数据": "#E5E7EB",
    "异常": "#8E8E93",
    "基载": "#4E79A7",
    "制冰": "#9C6ADE",
    "释冰": "#76B7B2",
    "释冰+基载": "#59A14F",
    "释冰+基载+双工况": "#F28E2B",
    "基载+双工况": "#EDC948",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_dir = args.input_dir
    timeseries_path = input_dir / "station_operation_modes_timeseries.csv"
    if not timeseries_path.exists():
        raise FileNotFoundError(timeseries_path)

    df = pd.read_csv(timeseries_path, encoding="utf-8-sig")
    df["collect_time_iso"] = pd.to_datetime(df["collect_time_iso"])
    df["date"] = df["collect_time_iso"].dt.date.astype(str)
    df["hour"] = df["collect_time_iso"].dt.hour + df["collect_time_iso"].dt.minute / 60.0
    plot_df = _expand_time_axis(df)

    image_path = input_dir / "station_operation_modes_visual_summary.png"
    html_path = input_dir / "station_operation_modes_visualization.html"
    _draw_dashboard(plot_df, image_path)
    _write_html(df, image_path, html_path)

    print(f"Wrote {image_path}")
    print(f"Wrote {html_path}")


def _draw_dashboard(df: pd.DataFrame, output_path: Path) -> None:
    width, height = 2100, 1260
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font_h2 = _font(40, bold=True)
    font_small = _font(28)

    _draw_mode_legend(draw, df, (1765, 115), font_small)
    _draw_timeline(draw, df, (80, 95, 1680, 260), font_h2, font_small)
    _draw_daily_stacked_bar(draw, df, (80, 365, 820, 765), font_h2, font_small)
    _draw_scatter(draw, df, (955, 365, 1680, 765), font_h2, font_small)
    _draw_load_and_ice(draw, df, (80, 875, 1680, 1185), font_h2, font_small)

    image.save(output_path)


def _draw_mode_legend(draw: ImageDraw.ImageDraw, df: pd.DataFrame, origin: tuple[int, int], font: ImageFont.ImageFont) -> None:
    x, y = origin
    modes = [mode for mode in MODE_COLORS if mode in set(df["operation_mode"])]
    draw.text((x, y - 46), "工况图例", fill="#111111", font=_font(34, bold=True), anchor="lm")
    for mode in modes:
        draw.rounded_rectangle((x, y, x + 34, y + 24), radius=5, fill=MODE_COLORS[mode])
        draw.text((x + 48, y + 12), mode, fill="#222222", font=font, anchor="lm")
        y += 52


def _draw_timeline(
    draw: ImageDraw.ImageDraw,
    df: pd.DataFrame,
    box: tuple[int, int, int, int],
    title_font: ImageFont.ImageFont,
    tick_font: ImageFont.ImageFont,
) -> None:
    x0, y0, x1, y1 = box
    draw.text(((x0 + x1) // 2, y0 - 35), "逐时刻工况时间轴", fill="#111111", font=title_font, anchor="ma")
    strip_y0, strip_y1 = y0 + 30, y1 - 40
    n = len(df)
    for i, mode in enumerate(df["operation_mode"]):
        xa = x0 + int(i * (x1 - x0) / n)
        xb = x0 + int((i + 1) * (x1 - x0) / n) + 1
        draw.rectangle((xa, strip_y0, xb, strip_y1), fill=MODE_COLORS.get(mode, "#CCCCCC"))
    draw.rectangle((x0, strip_y0, x1, strip_y1), outline="#222222", width=2)
    _draw_time_ticks(draw, df, x0, x1, strip_y1 + 8, tick_font)


def _draw_daily_stacked_bar(
    draw: ImageDraw.ImageDraw,
    df: pd.DataFrame,
    box: tuple[int, int, int, int],
    title_font: ImageFont.ImageFont,
    tick_font: ImageFont.ImageFont,
) -> None:
    x0, y0, x1, y1 = box
    draw.text(((x0 + x1) // 2, y0 - 35), "每日各工况持续时间", fill="#111111", font=title_font, anchor="ma")
    chart = (x0 + 80, y0 + 20, x1 - 20, y1 - 70)
    _draw_axes(draw, chart)
    dates = sorted(df["date"].unique())
    step_h = _median_step_h(df)
    max_h = 24.0
    bar_gap = 18
    bar_w = max(24, int((chart[2] - chart[0] - bar_gap * (len(dates) - 1)) / len(dates)))
    for idx, date in enumerate(dates):
        subset = df[df["date"] == date]
        counts = subset["operation_mode"].value_counts()
        x_left = chart[0] + idx * (bar_w + bar_gap)
        current_bottom = chart[3]
        for mode in MODE_COLORS:
            h = float(counts.get(mode, 0)) * step_h
            if h <= 0:
                continue
            seg_h = int(h / max_h * (chart[3] - chart[1]))
            draw.rectangle((x_left, current_bottom - seg_h, x_left + bar_w, current_bottom), fill=MODE_COLORS[mode])
            current_bottom -= seg_h
        draw.text((x_left + bar_w / 2, chart[3] + 12), _short_date_label(date), fill="#333333", font=tick_font, anchor="ma")
    for h in (0, 6, 12, 18, 24):
        yy = _map_value(h, 0, max_h, chart[3], chart[1])
        draw.line((chart[0] - 6, yy, chart[0], yy), fill="#333333", width=2)
        draw.text((chart[0] - 14, yy), str(h), fill="#333333", font=tick_font, anchor="rm")
    draw.text((chart[0] - 58, chart[1] - 24), "小时", fill="#333333", font=tick_font, anchor="mm")


def _draw_scatter(
    draw: ImageDraw.ImageDraw,
    df: pd.DataFrame,
    box: tuple[int, int, int, int],
    title_font: ImageFont.ImageFont,
    tick_font: ImageFont.ImageFont,
) -> None:
    x0, y0, x1, y1 = box
    draw.text(((x0 + x1) // 2, y0 - 35), "冷负荷-总功率工况分布", fill="#111111", font=title_font, anchor="ma")
    chart = (x0 + 85, y0 + 20, x1 - 30, y1 - 70)
    _draw_axes(draw, chart)
    observed = df[df["operation_mode"] != "无数据"].copy()
    x_min, x_max = 0.0, max(1.0, observed["cooling_load_kw"].max() * 1.05)
    y_min, y_max = 0.0, max(1.0, observed["power_kw"].max() * 1.08)
    for _, row in observed.iterrows():
        x = _map_value(row["cooling_load_kw"], x_min, x_max, chart[0], chart[2])
        y = _map_value(row["power_kw"], y_min, y_max, chart[3], chart[1])
        color = MODE_COLORS.get(row["operation_mode"], "#CCCCCC")
        draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill=color, outline=None)
    _draw_numeric_ticks(draw, chart, x_min, x_max, y_min, y_max, tick_font, "冷负荷(kW)", "总功率(kW)")


def _draw_load_and_ice(
    draw: ImageDraw.ImageDraw,
    df: pd.DataFrame,
    box: tuple[int, int, int, int],
    title_font: ImageFont.ImageFont,
    tick_font: ImageFont.ImageFont,
) -> None:
    x0, y0, x1, y1 = box
    draw.text(((x0 + x1) // 2, y0 - 35), "冷负荷与蓄冰量随时间变化", fill="#111111", font=title_font, anchor="ma")
    chart = (x0 + 85, y0 + 20, x1 - 85, y1 - 60)
    _draw_axes(draw, chart)

    n = len(df)
    observed = df[df["operation_mode"] != "无数据"].copy()
    step_h = _median_step_h(observed)
    ice_delta_column = "ice_delta_for_plot" if "ice_delta_for_plot" in observed else "ice_delta_per_step"
    ice_power_kw = _ice_discharge_power_kw(observed[ice_delta_column], step_h)
    value_min = min(0.0, float(ice_power_kw.min()) * 1.05)
    value_max = max(1.0, observed["cooling_load_kw"].max(), float(ice_power_kw.max())) * 1.05
    load_points = []
    ice_points = []
    for i, row in df.iterrows():
        x = chart[0] + int(i * (chart[2] - chart[0]) / max(1, n - 1))
        load_points.append(_point_or_gap(x, row["cooling_load_kw"], value_min, value_max, chart))
        ice_points.append(_point_or_gap(x, _ice_discharge_power_value(row.get(ice_delta_column), step_h), value_min, value_max, chart))
    _draw_line_segments(draw, load_points, fill="#1F77B4", width=4)
    _draw_line_segments(draw, ice_points, fill="#D62728", width=4)
    draw.text((chart[0] + 20, chart[1] + 14), "冷负荷(kW)", fill="#1F77B4", font=tick_font, anchor="lm")
    draw.text((chart[0] + 185, chart[1] + 14), "蓄冰释冷功率(kW)", fill="#D62728", font=tick_font, anchor="lm")
    _draw_time_ticks(draw, df, chart[0], chart[2], chart[3] + 8, tick_font)
    _draw_shared_y_ticks(draw, chart, value_min, value_max, tick_font, "kW")


def _write_html(df: pd.DataFrame, image_path: Path, html_path: Path) -> None:
    summary = (
        df.groupby("operation_mode")
        .agg(
            点数=("collect_time_iso", "count"),
            平均冷负荷=("cooling_load_kw", "mean"),
            平均负荷率=("load_ratio", "mean"),
            平均总功率=("power_kw", "mean"),
            平均流量=("flow_m3h", "mean"),
        )
        .reset_index()
        .sort_values("点数", ascending=False)
    )
    rows = []
    for _, row in summary.iterrows():
        color = MODE_COLORS.get(row["operation_mode"], "#CCCCCC")
        rows.append(
            "<tr>"
            f"<td><span class='swatch' style='background:{color}'></span>{html.escape(str(row['operation_mode']))}</td>"
            f"<td>{int(row['点数'])}</td>"
            f"<td>{row['平均冷负荷']:.2f}</td>"
            f"<td>{row['平均负荷率']:.3f}</td>"
            f"<td>{row['平均总功率']:.2f}</td>"
            f"<td>{row['平均流量']:.2f}</td>"
            "</tr>"
        )
    relative_image = image_path.name
    html_text = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>小梅沙冷站工况识别可视化</title>
  <style>
    body {{ margin: 0; font-family: "Microsoft YaHei", "SimHei", Arial, sans-serif; color: #1f2933; background: #f6f7f9; }}
    main {{ max-width: 1720px; margin: 0 auto; padding: 28px 36px 48px; }}
    img {{ width: 100%; border: 1px solid #d7dde5; background: white; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 28px; background: white; font-size: 16px; }}
    th, td {{ border: 1px solid #d7dde5; padding: 10px 12px; text-align: right; }}
    th:first-child, td:first-child {{ text-align: left; }}
    th {{ background: #eef2f6; }}
    .swatch {{ display: inline-block; width: 16px; height: 16px; border-radius: 3px; margin-right: 8px; vertical-align: -2px; }}
  </style>
</head>
<body>
<main>
  <img src="{relative_image}" alt="小梅沙冷站工况识别可视化">
  <table>
    <thead>
      <tr><th>工况</th><th>点数</th><th>平均冷负荷(kW)</th><th>平均负荷率</th><th>平均总功率(kW)</th><th>平均流量(m3/h)</th></tr>
    </thead>
    <tbody>
      {''.join(rows)}
    </tbody>
  </table>
</main>
</body>
</html>
"""
    html_path.write_text(html_text, encoding="utf-8")


def _draw_axes(draw: ImageDraw.ImageDraw, chart: tuple[int, int, int, int]) -> None:
    x0, y0, x1, y1 = chart
    draw.line((x0, y1, x1, y1), fill="#222222", width=2)
    draw.line((x0, y0, x0, y1), fill="#222222", width=2)
    for i in range(1, 5):
        yy = y1 - i * (y1 - y0) / 5
        draw.line((x0, yy, x1, yy), fill="#E5E7EB", width=1)


def _draw_time_ticks(
    draw: ImageDraw.ImageDraw,
    df: pd.DataFrame,
    x0: int,
    x1: int,
    y: int,
    font: ImageFont.ImageFont,
) -> None:
    dates = sorted(df["date"].unique())
    for date in dates:
        first_idx = int(df.index[df["date"] == date][0])
        x = x0 + int(first_idx * (x1 - x0) / max(1, len(df) - 1))
        draw.line((x, y - 8, x, y - 1), fill="#333333", width=2)
        draw.text((x, y + 4), date[5:], fill="#333333", font=font, anchor="ma")


def _draw_numeric_ticks(
    draw: ImageDraw.ImageDraw,
    chart: tuple[int, int, int, int],
    x_min: float,
    x_max: float,
    y_min: float,
    y_max: float,
    font: ImageFont.ImageFont,
    x_label: str,
    y_label: str,
) -> None:
    x0, y0, x1, y1 = chart
    for i in range(6):
        xv = x_min + (x_max - x_min) * i / 5
        x = _map_value(xv, x_min, x_max, x0, x1)
        draw.line((x, y1, x, y1 + 6), fill="#333333", width=2)
        draw.text((x, y1 + 10), f"{xv:.0f}", fill="#333333", font=font, anchor="ma")
        yv = y_min + (y_max - y_min) * i / 5
        y = _map_value(yv, y_min, y_max, y1, y0)
        draw.line((x0 - 6, y, x0, y), fill="#333333", width=2)
        draw.text((x0 - 12, y), f"{yv:.0f}", fill="#333333", font=font, anchor="rm")
    draw.text(((x0 + x1) // 2, y1 + 48), x_label, fill="#222222", font=font, anchor="ma")
    draw.text((x0 - 70, (y0 + y1) // 2), y_label, fill="#222222", font=font, anchor="mm")


def _draw_shared_y_ticks(
    draw: ImageDraw.ImageDraw,
    chart: tuple[int, int, int, int],
    y_min: float,
    y_max: float,
    font: ImageFont.ImageFont,
    label: str,
) -> None:
    x0, y0, x1, y1 = chart
    for i in range(5):
        value = y_min + (y_max - y_min) * i / 4
        y = _map_value(value, y_min, y_max, y1, y0)
        draw.line((x0 - 7, y, x0, y), fill="#333333", width=2)
        draw.text((x0 - 12, y), f"{value:.0f}", fill="#333333", font=font, anchor="rm")
    draw.text((x0 - 58, y0 - 22), label, fill="#333333", font=font, anchor="mm")


def _map_value(value: float, src_min: float, src_max: float, dst_min: float, dst_max: float) -> int:
    if src_max == src_min:
        return int((dst_min + dst_max) / 2)
    ratio = (float(value) - src_min) / (src_max - src_min)
    return int(dst_min + ratio * (dst_max - dst_min))


def _median_step_h(df: pd.DataFrame) -> float:
    delta = df["collect_time_iso"].sort_values().diff().dropna()
    if delta.empty:
        return 0.25
    return float(delta.median().total_seconds() / 3600)


def _short_date_label(date: str) -> str:
    month, day = date[5:].split("-")
    return f"{int(month)}/{int(day)}"


def _expand_time_axis(df: pd.DataFrame) -> pd.DataFrame:
    observed = df.sort_values("collect_time_iso").drop_duplicates("collect_time_iso", keep="last").copy()
    step = observed["collect_time_iso"].diff().dropna().median()
    if pd.isna(step) or step <= pd.Timedelta(0):
        step = pd.Timedelta(minutes=15)
    start = observed["collect_time_iso"].min().normalize()
    end = observed["collect_time_iso"].max().normalize() + pd.Timedelta(days=1) - step
    full_time = pd.date_range(start=start, end=end, freq=step)
    expanded = (
        observed.set_index("collect_time_iso")
        .reindex(full_time)
        .rename_axis("collect_time_iso")
        .reset_index()
    )
    expanded["date"] = expanded["collect_time_iso"].dt.date.astype(str)
    expanded["hour"] = expanded["collect_time_iso"].dt.hour + expanded["collect_time_iso"].dt.minute / 60.0
    expanded["operation_mode"] = expanded["operation_mode"].fillna("无数据")
    expanded["mode_reason"] = expanded["mode_reason"].fillna("该时段原始表中没有实测数据")
    expanded["ice_delta_for_plot"] = pd.to_numeric(expanded["ice_inventory"], errors="coerce").diff()
    return expanded


def _point_or_gap(
    x: int,
    value: float,
    src_min: float,
    src_max: float,
    chart: tuple[int, int, int, int],
) -> tuple[int, int] | None:
    if pd.isna(value):
        return None
    return (x, _map_value(value, src_min, src_max, chart[3], chart[1]))


def _ice_discharge_power_kw(delta_rt: pd.Series, step_h: float) -> pd.Series:
    step = max(step_h, 1e-9)
    return -pd.to_numeric(delta_rt, errors="coerce") * RT_TO_KW / step


def _ice_discharge_power_value(delta_rt: float, step_h: float) -> float:
    if pd.isna(delta_rt):
        return float("nan")
    return -float(delta_rt) * RT_TO_KW / max(step_h, 1e-9)


def _draw_line_segments(
    draw: ImageDraw.ImageDraw,
    points: list[tuple[int, int] | None],
    fill: str,
    width: int,
) -> None:
    segment: list[tuple[int, int]] = []
    for point in points:
        if point is None:
            if len(segment) >= 2:
                draw.line(segment, fill=fill, width=width)
            segment = []
        else:
            segment.append(point)
    if len(segment) >= 2:
        draw.line(segment, fill=fill, width=width)


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
