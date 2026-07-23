"""Draw cooling-load and remaining ice inventory comparison."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from PIL import Image, ImageDraw, ImageFont


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INPUT = PROJECT_ROOT / "data" / "processed" / "operation_mode_identification" / "station_operation_modes_timeseries.csv"
OUTPUT = PROJECT_ROOT / "data" / "processed" / "operation_mode_identification" / "ice_inventory_vs_cooling_load.png"
RT_H_TO_KWH = 3.517


def main() -> None:
    df = pd.read_csv(INPUT, encoding="utf-8-sig")
    df["collect_time_iso"] = pd.to_datetime(df["collect_time_iso"])
    df = _expand_time_axis(df)
    _draw(df, OUTPUT)
    print(OUTPUT)


def _expand_time_axis(df: pd.DataFrame) -> pd.DataFrame:
    observed = df.sort_values("collect_time_iso").drop_duplicates("collect_time_iso", keep="last").copy()
    step = observed["collect_time_iso"].diff().dropna().median()
    if pd.isna(step) or step <= pd.Timedelta(0):
        step = pd.Timedelta(minutes=15)
    start = observed["collect_time_iso"].min().normalize()
    end = observed["collect_time_iso"].max().normalize() + pd.Timedelta(days=1) - step
    full_time = pd.date_range(start=start, end=end, freq=step)
    return (
        observed.set_index("collect_time_iso")
        .reindex(full_time)
        .rename_axis("collect_time_iso")
        .reset_index()
    )


def _draw(df: pd.DataFrame, path: Path) -> None:
    width, height = 1900, 900
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    title_font = _font(44, bold=True)
    font = _font(28)
    small = _font(24)

    chart = (150, 150, 1680, 720)
    draw.text(((chart[0] + chart[2]) // 2, 70), "冷负荷与冰剩余量对比", fill="#111111", font=title_font, anchor="ma")
    _draw_axes(draw, chart)

    observed = df.dropna(subset=["cooling_load_kw", "ice_inventory"]).copy()
    load_min, load_max = 0.0, max(1.0, float(observed["cooling_load_kw"].max()) * 1.08)
    ice_kwh = pd.to_numeric(observed["ice_inventory"], errors="coerce") * RT_H_TO_KWH
    ice_min = float(ice_kwh.min() * 0.96)
    ice_max = float(ice_kwh.max() * 1.04)

    load_points: list[tuple[int, int] | None] = []
    ice_points: list[tuple[int, int] | None] = []
    n = len(df)
    for i, row in df.iterrows():
        x = chart[0] + int(i * (chart[2] - chart[0]) / max(1, n - 1))
        load_points.append(_point_or_gap(x, row.get("cooling_load_kw"), load_min, load_max, chart))
        ice_value = row.get("ice_inventory")
        if pd.notna(ice_value):
            ice_value = float(ice_value) * RT_H_TO_KWH
        ice_points.append(_point_or_gap(x, ice_value, ice_min, ice_max, chart))

    _draw_line_segments(draw, load_points, fill="#1F77B4", width=4)
    _draw_line_segments(draw, ice_points, fill="#D62728", width=4)
    _draw_time_ticks(draw, df, chart, small)
    _draw_dual_ticks(draw, chart, load_min, load_max, ice_min, ice_max, small)

    draw.text((chart[0] + 20, chart[1] + 18), "冷负荷(kW)", fill="#1F77B4", font=font, anchor="lm")
    draw.text((chart[0] + 210, chart[1] + 18), "冰剩余量(kWh)", fill="#D62728", font=font, anchor="lm")
    note = "注：冰剩余量由原始冰库存数据换算，1 RT·h = 3.517 kWh；缺测时段曲线断开。"
    draw.text(((chart[0] + chart[2]) // 2, 820), note, fill="#4B5563", font=small, anchor="ma")
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def _draw_axes(draw: ImageDraw.ImageDraw, chart: tuple[int, int, int, int]) -> None:
    x0, y0, x1, y1 = chart
    draw.line((x0, y1, x1, y1), fill="#222222", width=2)
    draw.line((x0, y0, x0, y1), fill="#222222", width=2)
    draw.line((x1, y0, x1, y1), fill="#222222", width=2)
    for i in range(1, 5):
        yy = y1 - i * (y1 - y0) / 5
        draw.line((x0, yy, x1, yy), fill="#E5E7EB", width=1)


def _draw_dual_ticks(
    draw: ImageDraw.ImageDraw,
    chart: tuple[int, int, int, int],
    load_min: float,
    load_max: float,
    ice_min: float,
    ice_max: float,
    font: ImageFont.ImageFont,
) -> None:
    x0, y0, x1, y1 = chart
    for i in range(5):
        ratio = i / 4
        y = int(y1 - ratio * (y1 - y0))
        load_value = load_min + ratio * (load_max - load_min)
        ice_value = ice_min + ratio * (ice_max - ice_min)
        draw.line((x0 - 7, y, x0, y), fill="#1F77B4", width=2)
        draw.text((x0 - 12, y), f"{load_value:.0f}", fill="#1F77B4", font=font, anchor="rm")
        draw.line((x1, y, x1 + 7, y), fill="#D62728", width=2)
        draw.text((x1 + 12, y), f"{ice_value:.0f}", fill="#D62728", font=font, anchor="lm")


def _draw_time_ticks(draw: ImageDraw.ImageDraw, df: pd.DataFrame, chart: tuple[int, int, int, int], font: ImageFont.ImageFont) -> None:
    x0, _, x1, y1 = chart
    dates = sorted(df["collect_time_iso"].dt.date.astype(str).unique())
    for date in dates:
        first_idx = int(df.index[df["collect_time_iso"].dt.date.astype(str) == date][0])
        x = x0 + int(first_idx * (x1 - x0) / max(1, len(df) - 1))
        draw.line((x, y1, x, y1 + 8), fill="#333333", width=2)
        draw.text((x, y1 + 16), date[5:], fill="#333333", font=font, anchor="ma")


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


def _map_value(value: float, src_min: float, src_max: float, dst_min: float, dst_max: float) -> int:
    if src_max == src_min:
        return int((dst_min + dst_max) / 2)
    ratio = (float(value) - src_min) / (src_max - src_min)
    return int(dst_min + ratio * (dst_max - dst_min))


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        Path("C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
    ]
    for font_path in candidates:
        if font_path.exists():
            return ImageFont.truetype(str(font_path), size=size)
    return ImageFont.load_default()


if __name__ == "__main__":
    main()
