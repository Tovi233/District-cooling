from __future__ import annotations

from pathlib import Path

import pandas as pd
from PIL import Image, ImageDraw, ImageFont


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INPUT_DIR = PROJECT_ROOT / "data" / "processed" / "station_flexibility_potential"
OUTPUT_PATH = INPUT_DIR / "station_rebound_related_parameters.png"

MODE_MAP = {
    "�Ʊ�": "制冰",
    "����": "基载",
    "����+˫����": "基载+双工况",
    "�ͱ�+����": "释冰+基载",
    "�ͱ�+����+˫����": "释冰+基载+双工况",
}

W, H = 2600, 1650


def main() -> None:
    df = pd.read_csv(INPUT_DIR / "station_flexibility_timeseries.csv", encoding="utf-8-sig")
    df["collect_time_iso"] = pd.to_datetime(df["collect_time_iso"])
    df["operation_mode_cn"] = df["operation_mode"].map(MODE_MAP).fillna(df["operation_mode"])

    image = Image.new("RGB", (W, H), "white")
    draw = ImageDraw.Draw(image)
    fonts = {
        "title": _font(54, bold=True),
        "h2": _font(34, bold=True),
        "normal": _font(26),
        "small": _font(22),
        "tiny": _font(18),
    }

    _center_text(draw, "反弹功率及相关参数可视化", W // 2, 48, fonts["title"], "#111111")
    _draw_power_panel(draw, df, (90, 150, 1680, 560), fonts)
    _draw_energy_panel(draw, df, (90, 680, 1680, 1090), fonts)
    _draw_scatter_panel(draw, df, (1780, 150, 2480, 780), fonts)
    _draw_mode_panel(draw, df, (1780, 900, 2480, 1455), fonts)
    _draw_formula_note(draw, (90, 1245, 1680, 1455), fonts)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    image.save(OUTPUT_PATH, quality=95)
    print(OUTPUT_PATH)


def _draw_power_panel(draw: ImageDraw.ImageDraw, df: pd.DataFrame, box: tuple[int, int, int, int], fonts: dict) -> None:
    x0, y0, x1, y1 = box
    _center_text(draw, "反弹功率与可削减功率", (x0 + x1) // 2, y0 - 38, fonts["h2"], "#111111")
    chart = (x0 + 120, y0 + 35, x1 - 45, y1 - 70)
    _axes(draw, chart)
    y_max = max(float(df["rebound_power_kw"].max()), float(df["reducible_power_kw"].max()), 1.0) * 1.12
    draw.line(_series_points(df["reducible_power_kw"], chart, 0, y_max), fill="#1F77B4", width=4)
    draw.line(_series_points(df["rebound_power_kw"], chart, 0, y_max), fill="#D62728", width=4)
    _y_ticks(draw, chart, 0, y_max, fonts["tiny"], "功率 (kW)")
    _time_ticks(draw, df, chart, fonts["tiny"])
    _legend(draw, chart[0] + 28, chart[1] + 16, [("可削减功率", "#1F77B4"), ("反弹功率", "#D62728")], fonts["small"])


def _draw_energy_panel(draw: ImageDraw.ImageDraw, df: pd.DataFrame, box: tuple[int, int, int, int], fonts: dict) -> None:
    x0, y0, x1, y1 = box
    _center_text(draw, "可转移冷量与可用蓄冰冷量", (x0 + x1) // 2, y0 - 38, fonts["h2"], "#111111")
    chart = (x0 + 130, y0 + 35, x1 - 45, y1 - 70)
    _axes(draw, chart)
    y_max = max(float(df["usable_ice_energy_kwh"].max()), float(df["transferable_cooling_energy_kwh"].max()), 1.0) * 1.08
    draw.line(_series_points(df["usable_ice_energy_kwh"], chart, 0, y_max), fill="#2E7D32", width=4)
    draw.line(_series_points(df["transferable_cooling_energy_kwh"], chart, 0, y_max), fill="#FF7F0E", width=4)
    _y_ticks(draw, chart, 0, y_max, fonts["tiny"], "冷量 (kWh)")
    _time_ticks(draw, df, chart, fonts["tiny"])
    _legend(draw, chart[0] + 28, chart[1] + 16, [("可用蓄冰冷量", "#2E7D32"), ("可转移冷量", "#FF7F0E")], fonts["small"])


def _draw_scatter_panel(draw: ImageDraw.ImageDraw, df: pd.DataFrame, box: tuple[int, int, int, int], fonts: dict) -> None:
    x0, y0, x1, y1 = box
    draw.rounded_rectangle(box, radius=18, fill="#F8FAFC", outline="#D5DEE8", width=2)
    _center_text(draw, "反弹与可转移冷量关系", (x0 + x1) // 2, y0 + 22, fonts["h2"], "#111111")
    chart = (x0 + 95, y0 + 95, x1 - 60, y1 - 100)
    _axes(draw, chart)
    x_max = max(float(df["transferable_cooling_energy_kwh"].max()), 1.0) * 1.08
    y_max = max(float(df["rebound_power_kw"].max()), 1.0) * 1.12
    sample = df[["transferable_cooling_energy_kwh", "rebound_power_kw"]].dropna()
    for _, row in sample.iloc[:: max(1, len(sample) // 420)].iterrows():
        px = chart[0] + int(float(row["transferable_cooling_energy_kwh"]) / x_max * (chart[2] - chart[0]))
        py = chart[3] - int(float(row["rebound_power_kw"]) / y_max * (chart[3] - chart[1]))
        draw.ellipse((px - 3, py - 3, px + 3, py + 3), fill="#D62728")
    _x_ticks(draw, chart, 0, x_max, fonts["tiny"], "可转移冷量 (kWh)")
    _y_ticks(draw, chart, 0, y_max, fonts["tiny"], "反弹功率 (kW)")

    corr = sample["transferable_cooling_energy_kwh"].corr(sample["rebound_power_kw"])
    draw.text((x0 + 40, y1 - 62), f"相关系数 r = {corr:.3f}", font=fonts["small"], fill="#334155")
    draw.text((x0 + 40, y1 - 32), "反弹功率随可转移冷量近似线性增加", font=fonts["tiny"], fill="#64748B")


def _draw_mode_panel(draw: ImageDraw.ImageDraw, df: pd.DataFrame, box: tuple[int, int, int, int], fonts: dict) -> None:
    x0, y0, x1, y1 = box
    draw.rounded_rectangle(box, radius=18, fill="#F8FAFC", outline="#D5DEE8", width=2)
    _center_text(draw, "分工况平均反弹功率", (x0 + x1) // 2, y0 + 22, fonts["h2"], "#111111")
    chart = (x0 + 245, y0 + 95, x1 - 85, y1 - 75)
    _axes(draw, chart)
    order = ["制冰", "基载", "基载+双工况", "释冰+基载", "释冰+基载+双工况"]
    summary = (
        df.groupby("operation_mode_cn")
        .agg(mean_rebound=("rebound_power_kw", "mean"), mean_transfer=("transferable_cooling_energy_kwh", "mean"))
        .reindex(order)
        .dropna()
        .reset_index()
    )
    max_v = max(float(summary["mean_rebound"].max()), 1.0) * 1.15
    bar_h = 42
    gap = 32
    for i, row in summary.iterrows():
        y = chart[1] + i * (bar_h + gap)
        value = float(row["mean_rebound"])
        width = int(value / max_v * (chart[2] - chart[0]))
        draw.text((chart[0] - 16, y + bar_h / 2), str(row["operation_mode_cn"]), font=fonts["tiny"], fill="#222222", anchor="rm")
        draw.rectangle((chart[0], y, chart[0] + width, y + bar_h), fill="#D62728")
        draw.text((chart[0] + width + 12, y + bar_h / 2), f"{value:.0f}", font=fonts["tiny"], fill="#222222", anchor="lm")
    _center_text(draw, "平均反弹功率 (kW)", (chart[0] + chart[2]) // 2, chart[3] + 34, fonts["tiny"], "#333333")


def _draw_formula_note(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], fonts: dict) -> None:
    x0, y0, x1, y1 = box
    draw.rounded_rectangle(box, radius=18, fill="#FFF7ED", outline="#FDBA74", width=2)
    draw.text((x0 + 36, y0 + 28), "当前模型中反弹的含义", font=fonts["h2"], fill="#111111")
    lines = [
        "反弹功率表示：响应后为了恢复蓄冰量，需要在后续恢复阶段补回的制冰功率。",
        "计算关系：反弹功率 = 可转移冷量 / 制冰COP / 恢复时长。",
        "因此，反弹功率主要由可转移冷量决定；可转移冷量越大，后续需要补制冰的功率越高。",
        "当前暂不计入用户侧升温响应，所以这里不是建筑室温恢复反弹，而是冷站蓄冰恢复反弹。",
    ]
    y = y0 + 88
    for line in lines:
        draw.text((x0 + 42, y), line, font=fonts["normal"], fill="#334155")
        y += 44


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
    return y1 - int((value - v_min) / (v_max - v_min) * (y1 - y0))


def _axes(draw: ImageDraw.ImageDraw, chart: tuple[int, int, int, int]) -> None:
    x0, y0, x1, y1 = chart
    draw.line((x0, y1, x1, y1), fill="#222222", width=3)
    draw.line((x0, y0, x0, y1), fill="#222222", width=3)
    for i in range(1, 5):
        y = y1 - i * (y1 - y0) / 5
        draw.line((x0, y, x1, y), fill="#E5E7EB", width=1)


def _x_ticks(draw: ImageDraw.ImageDraw, chart: tuple[int, int, int, int], v_min: float, v_max: float, font: ImageFont.ImageFont, label: str) -> None:
    x0, _, x1, y1 = chart
    for i in range(5):
        value = v_min + (v_max - v_min) * i / 4
        x = x0 + int((value - v_min) / (v_max - v_min) * (x1 - x0))
        draw.line((x, y1, x, y1 + 8), fill="#222222", width=2)
        draw.text((x, y1 + 14), f"{value:.0f}", font=font, fill="#333333", anchor="ma")
    _center_text(draw, label, (x0 + x1) // 2, y1 + 48, font, "#333333")


def _y_ticks(draw: ImageDraw.ImageDraw, chart: tuple[int, int, int, int], v_min: float, v_max: float, font: ImageFont.ImageFont, label: str) -> None:
    x0, y0, _, y1 = chart
    for i in range(5):
        value = v_min + (v_max - v_min) * i / 4
        y = _value_y(value, v_min, v_max, y0, y1)
        draw.line((x0 - 8, y, x0, y), fill="#222222", width=2)
        draw.text((x0 - 14, y), f"{value:.0f}", font=font, fill="#333333", anchor="rm")
    draw.text((x0 - 96, y0 - 26), label, font=font, fill="#333333")


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
        x += 245


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
