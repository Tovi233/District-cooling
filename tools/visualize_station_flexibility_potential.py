"""Draw a visual summary for station-side flexibility-potential results."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from PIL import Image, ImageDraw, ImageFont


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_DIR = PROJECT_ROOT / "data" / "processed" / "station_flexibility_potential"

LEVEL_COLORS = {
    "可响应": "#2CA02C",
    "谨慎响应": "#FFB000",
    "不建议响应": "#A6A6A6",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    timeseries_path = args.input_dir / "station_flexibility_timeseries.csv"
    summary_path = args.input_dir / "station_flexibility_summary.csv"
    if not timeseries_path.exists():
        raise FileNotFoundError(timeseries_path)
    df = pd.read_csv(timeseries_path, encoding="utf-8-sig")
    summary = pd.read_csv(summary_path, encoding="utf-8-sig") if summary_path.exists() else pd.DataFrame()
    df["collect_time_iso"] = pd.to_datetime(df["collect_time_iso"])

    output_path = args.input_dir / "station_flexibility_visual_summary.png"
    _draw_dashboard(df, summary, output_path)
    print(f"Wrote {output_path}")


def _draw_dashboard(df: pd.DataFrame, summary: pd.DataFrame, output_path: Path) -> None:
    width, height = 2100, 1300
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font_title = _font(46, bold=True)
    font = _font(30)
    font_small = _font(24)

    draw.text((width // 2, 45), "冷站侧可调潜力估算", fill="#111111", font=font_title, anchor="ma")
    _draw_time_series(draw, df, (90, 135, 1560, 450), font, font_small)
    _draw_duration_bars(draw, summary, (90, 560, 900, 1120), font, font_small)
    _draw_level_pie(draw, df, (1120, 560, 1560, 1000), font, font_small)
    _draw_key_metrics(draw, df, (1650, 160), font, font_small)
    image.save(output_path)


def _draw_time_series(
    draw: ImageDraw.ImageDraw,
    df: pd.DataFrame,
    box: tuple[int, int, int, int],
    font: ImageFont.ImageFont,
    font_small: ImageFont.ImageFont,
) -> None:
    x0, y0, x1, y1 = box
    draw.text(((x0 + x1) // 2, y0 - 25), "当前总功率与可削减功率", fill="#111111", font=font, anchor="ma")
    chart = (x0 + 90, y0 + 25, x1 - 20, y1 - 60)
    _draw_axes(draw, chart)
    y_max = max(float(df["power_kw"].max()), float(df["reducible_power_kw"].max()), 1.0) * 1.08
    power_points = _series_points(df["power_kw"], chart, 0, y_max)
    reducible_points = _series_points(df["reducible_power_kw"], chart, 0, y_max)
    draw.line(power_points, fill="#1F77B4", width=4)
    draw.line(reducible_points, fill="#D62728", width=4)
    _draw_y_ticks(draw, chart, 0, y_max, font_small, "kW")
    _draw_time_ticks(draw, df, chart, font_small)
    draw.text((chart[0] + 20, chart[1] + 12), "总功率", fill="#1F77B4", font=font_small, anchor="lm")
    draw.text((chart[0] + 130, chart[1] + 12), "可削减功率", fill="#D62728", font=font_small, anchor="lm")


def _draw_duration_bars(
    draw: ImageDraw.ImageDraw,
    summary: pd.DataFrame,
    box: tuple[int, int, int, int],
    font: ImageFont.ImageFont,
    font_small: ImageFont.ImageFont,
) -> None:
    x0, y0, x1, y1 = box
    draw.text(((x0 + x1) // 2, y0 - 25), "分工况平均可削减功率", fill="#111111", font=font, anchor="ma")
    chart = (x0 + 250, y0 + 25, x1 - 25, y1 - 45)
    _draw_axes(draw, chart)
    if summary.empty:
        return
    rows = summary.sort_values("mean_reducible_power_kw", ascending=True).tail(8)
    max_value = max(float(rows["mean_reducible_power_kw"].max()), 1.0) * 1.1
    bar_h = max(24, int((chart[3] - chart[1]) / max(len(rows), 1) * 0.58))
    gap = max(12, int((chart[3] - chart[1] - bar_h * len(rows)) / max(len(rows), 1)))
    for idx, (_, row) in enumerate(rows.iterrows()):
        y = chart[1] + idx * (bar_h + gap)
        value = float(row["mean_reducible_power_kw"])
        bar_w = int(value / max_value * (chart[2] - chart[0]))
        color = LEVEL_COLORS.get(str(row["response_level"]), "#A6A6A6")
        label = f"{row['operation_mode']} / {row['response_level']}"
        draw.text((chart[0] - 12, y + bar_h / 2), label, fill="#222222", font=font_small, anchor="rm")
        draw.rectangle((chart[0], y, chart[0] + bar_w, y + bar_h), fill=color)
        draw.text((chart[0] + bar_w + 8, y + bar_h / 2), f"{value:.0f}", fill="#222222", font=font_small, anchor="lm")
    draw.text(((chart[0] + chart[2]) // 2, chart[3] + 22), "平均可削减功率(kW)", fill="#222222", font=font_small, anchor="ma")


def _draw_level_pie(
    draw: ImageDraw.ImageDraw,
    df: pd.DataFrame,
    box: tuple[int, int, int, int],
    font: ImageFont.ImageFont,
    font_small: ImageFont.ImageFont,
) -> None:
    x0, y0, x1, y1 = box
    draw.text(((x0 + x1) // 2, y0 - 25), "响应等级占比", fill="#111111", font=font, anchor="ma")
    counts = df["response_level"].value_counts()
    total = max(int(counts.sum()), 1)
    start = -90
    cx, cy, r = (x0 + x1) // 2 - 60, (y0 + y1) // 2, 160
    for level in LEVEL_COLORS:
        count = int(counts.get(level, 0))
        end = start + 360 * count / total
        draw.pieslice((cx - r, cy - r, cx + r, cy + r), start=start, end=end, fill=LEVEL_COLORS[level])
        start = end
    lx, ly = cx + 230, cy - 100
    for level, color in LEVEL_COLORS.items():
        count = int(counts.get(level, 0))
        draw.rectangle((lx, ly, lx + 28, ly + 20), fill=color)
        draw.text((lx + 42, ly + 10), f"{level}: {count} 点", fill="#222222", font=font_small, anchor="lm")
        ly += 48


def _draw_key_metrics(
    draw: ImageDraw.ImageDraw,
    df: pd.DataFrame,
    origin: tuple[int, int],
    font: ImageFont.ImageFont,
    font_small: ImageFont.ImageFont,
) -> None:
    x, y = origin
    metrics = [
        ("平均冷负荷", df["cooling_load_kw"].mean(), "kW"),
        ("平均总功率", df["power_kw"].mean(), "kW"),
        ("平均可削减功率", df["reducible_power_kw"].mean(), "kW"),
        ("最大可削减功率", df["reducible_power_kw"].max(), "kW"),
        ("平均响应时长", df["response_duration_h"].mean(), "h"),
        ("平均反弹功率", df["rebound_power_kw"].mean(), "kW"),
    ]
    draw.text((x, y - 40), "关键指标", fill="#111111", font=font, anchor="la")
    for label, value, unit in metrics:
        draw.text((x, y), label, fill="#333333", font=font_small, anchor="la")
        draw.text((x + 320, y), f"{value:.1f} {unit}", fill="#111111", font=font_small, anchor="ra")
        y += 52


def _draw_axes(draw: ImageDraw.ImageDraw, chart: tuple[int, int, int, int]) -> None:
    x0, y0, x1, y1 = chart
    draw.line((x0, y1, x1, y1), fill="#222222", width=2)
    draw.line((x0, y0, x0, y1), fill="#222222", width=2)
    for i in range(1, 5):
        yy = y1 - i * (y1 - y0) / 5
        draw.line((x0, yy, x1, yy), fill="#E5E7EB", width=1)


def _series_points(values: pd.Series, chart: tuple[int, int, int, int], y_min: float, y_max: float) -> list[tuple[int, int]]:
    x0, y0, x1, y1 = chart
    n = len(values)
    points = []
    for i, value in enumerate(values):
        x = x0 + int(i * (x1 - x0) / max(n - 1, 1))
        y = _map_value(float(value), y_min, y_max, y1, y0)
        points.append((x, y))
    return points


def _draw_y_ticks(
    draw: ImageDraw.ImageDraw,
    chart: tuple[int, int, int, int],
    y_min: float,
    y_max: float,
    font: ImageFont.ImageFont,
    unit: str,
) -> None:
    x0, y0, _, y1 = chart
    for i in range(5):
        value = y_min + (y_max - y_min) * i / 4
        y = _map_value(value, y_min, y_max, y1, y0)
        draw.line((x0 - 7, y, x0, y), fill="#333333", width=2)
        draw.text((x0 - 12, y), f"{value:.0f}", fill="#333333", font=font, anchor="rm")
    draw.text((x0 - 58, y0 - 20), unit, fill="#333333", font=font, anchor="mm")


def _draw_time_ticks(
    draw: ImageDraw.ImageDraw,
    df: pd.DataFrame,
    chart: tuple[int, int, int, int],
    font: ImageFont.ImageFont,
) -> None:
    x0, _, x1, y1 = chart
    dates = df["collect_time_iso"].dt.date.astype(str)
    for date in sorted(dates.unique()):
        first_idx = int(dates[dates == date].index[0])
        x = x0 + int(first_idx * (x1 - x0) / max(len(df) - 1, 1))
        draw.line((x, y1, x, y1 + 7), fill="#333333", width=2)
        draw.text((x, y1 + 12), date[5:], fill="#333333", font=font, anchor="ma")
    draw.text(((x0 + x1) // 2, y1 + 48), "Time", fill="#222222", font=font, anchor="ma")


def _map_value(value: float, src_min: float, src_max: float, dst_min: float, dst_max: float) -> int:
    if src_max == src_min:
        return int((dst_min + dst_max) / 2)
    ratio = (value - src_min) / (src_max - src_min)
    return int(dst_min + ratio * (dst_max - dst_min))


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
