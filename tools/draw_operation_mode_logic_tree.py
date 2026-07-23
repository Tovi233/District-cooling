"""Draw a top-down operation-mode decision tree."""

from __future__ import annotations

from pathlib import Path
from textwrap import wrap

from PIL import Image, ImageDraw, ImageFont


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "data" / "processed" / "operation_mode_identification"
OUTPUT_PATH = OUTPUT_DIR / "operation_mode_logic_tree.png"


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (2800, 1900), "white")
    draw = ImageDraw.Draw(image)

    title_font = _font(54, bold=True)
    box_font = _font(32, bold=True)
    note_font = _font(27)
    edge_font = _font(28, bold=True)

    draw.text((1300, 58), "冷站工况识别逻辑树", fill="#111827", font=title_font, anchor="ma")
    draw.text(
        (1300, 122),
        "先判断制冰，再判断释冰，最后按冷水机组运行组合归类",
        fill="#4B5563",
        font=note_font,
        anchor="ma",
    )

    nodes = {
        "start": (1300, 210, "开始\n读取当前时刻数据", "start"),
        "standby": (1300, 390, "是否停机/无效？\n负荷<500kW且主冷机未运行\n或流量<300m3/h", "decision"),
        "abnormal_top": (1900, 390, "异常", "end_bad"),
        "ice_making": (1300, 630, "是否制冰？\ndual_chiller_on_count >= 1\n且 dual_min_chw_out_temp_c < 0°C", "decision"),
        "ice": (1900, 630, "制冰", "end"),
        "discharge": (1300, 870, "是否释冰？\nice_delta_per_step < -50", "decision"),
        "d_base": (650, 1120, "基载机组是否运行？\nbase_chiller_on_count >= 1", "decision"),
        "m_base": (1950, 1120, "基载机组是否运行？\nbase_chiller_on_count >= 1", "decision"),
        "d_base_dual": (480, 1370, "双工况机组是否运行？\ndual_chiller_on_count >= 1", "decision"),
        "m_base_dual": (1720, 1370, "双工况机组是否运行？\ndual_chiller_on_count >= 1", "decision"),
        "ice_base": (260, 1620, "释冰+基载", "end"),
        "ice_base_dual": (700, 1620, "释冰+基载+双工况", "end"),
        "ice_only": (1080, 1620, "释冰", "end"),
        "base": (1500, 1620, "基载", "end"),
        "base_dual": (1900, 1620, "基载+双工况", "end"),
        "m_abnormal": (2300, 1620, "异常", "end_bad"),
    }

    edges = [
        ("start", "standby", ""),
        ("standby", "abnormal_top", "Yes"),
        ("standby", "ice_making", "No"),
        ("ice_making", "ice", "Yes"),
        ("ice_making", "discharge", "No"),
        ("discharge", "d_base", "Yes"),
        ("discharge", "m_base", "No"),
        ("d_base", "d_base_dual", "Yes"),
        ("d_base", "ice_only", "No"),
        ("d_base_dual", "ice_base_dual", "Yes"),
        ("d_base_dual", "ice_base", "No"),
        ("m_base", "m_base_dual", "Yes"),
        ("m_base", "m_abnormal", "No"),
        ("m_base_dual", "base_dual", "Yes"),
        ("m_base_dual", "base", "No"),
    ]

    for src, dst, label in edges:
        _arrow(draw, _port(nodes[src], nodes[dst]), label, edge_font)

    for node in nodes.values():
        _node(draw, node, box_font)

    footer = (
        "说明：ice_delta_per_step > 50 不再作为异常判据；若未满足制冰/释冰条件，"
        "则按当前冷水机组运行组合归类。"
    )
    draw.text((1300, 1818), footer, fill="#4B5563", font=note_font, anchor="ma")
    image.save(OUTPUT_PATH)
    print(OUTPUT_PATH)


def _node(draw: ImageDraw.ImageDraw, node: tuple[int, int, str, str], font: ImageFont.ImageFont) -> None:
    x, y, text, kind = node
    if kind == "start":
        fill, outline, size = "#EEF6FF", "#2563EB", (410, 110)
    elif kind == "decision":
        fill, outline, size = "#F8FAFC", "#334155", (520, 150)
    elif kind == "end_bad":
        fill, outline, size = "#F3F4F6", "#6B7280", (260, 100)
    else:
        fill, outline, size = "#ECFDF5", "#059669", (300, 100)

    w, h = size
    box = (x - w // 2, y - h // 2, x + w // 2, y + h // 2)
    draw.rounded_rectangle(box, radius=18, fill=fill, outline=outline, width=4)
    lines = []
    for part in text.split("\n"):
        lines.extend(wrap(part, width=24) or [""])
    line_h = 36
    start_y = y - (len(lines) - 1) * line_h / 2
    for i, line in enumerate(lines):
        draw.text((x, start_y + i * line_h), line, fill="#111827", font=font, anchor="mm")


def _port(src: tuple[int, int, str, str], dst: tuple[int, int, str, str]) -> tuple[int, int, int, int]:
    sx, sy, _, _ = src
    dx, dy, _, _ = dst
    if abs(dx - sx) > abs(dy - sy):
        start_x = sx + (260 if dx > sx else -260)
        start_y = sy
        end_x = dx - (180 if dx > sx else -180)
        end_y = dy
    else:
        start_x = sx
        start_y = sy + 78
        end_x = dx
        end_y = dy - 78
    return int(start_x), int(start_y), int(end_x), int(end_y)


def _arrow(draw: ImageDraw.ImageDraw, line: tuple[int, int, int, int], label: str, font: ImageFont.ImageFont) -> None:
    x0, y0, x1, y1 = line
    draw.line((x0, y0, x1, y1), fill="#374151", width=4)
    dx = x1 - x0
    dy = y1 - y0
    length = max((dx * dx + dy * dy) ** 0.5, 1)
    ux, uy = dx / length, dy / length
    px, py = -uy, ux
    tip = (x1, y1)
    p1 = (x1 - ux * 22 + px * 10, y1 - uy * 22 + py * 10)
    p2 = (x1 - ux * 22 - px * 10, y1 - uy * 22 - py * 10)
    draw.polygon([tip, p1, p2], fill="#374151")
    if label:
        lx = (x0 + x1) / 2 + px * 20
        ly = (y0 + y1) / 2 + py * 20
        draw.rounded_rectangle((lx - 42, ly - 20, lx + 42, ly + 20), radius=10, fill="white", outline="#CBD5E1", width=2)
        draw.text((lx, ly), label, fill="#111827", font=font, anchor="mm")


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
