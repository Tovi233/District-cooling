from pathlib import Path
import math

from PIL import Image, ImageDraw, ImageFont


OUT_PATH = Path(__file__).resolve().parents[1] / "outputs" / "冷站侧可调潜力逻辑树_透明背景.png"
FONT_PATH = Path("C:/Windows/Fonts/msyh.ttc")

W, H = 1900, 2340

COLORS = {
    "text": (24, 35, 48, 255),
    "title": (18, 52, 86, 255),
    "line": (42, 83, 145, 255),
    "input_fill": (225, 239, 255, 242),
    "calc_fill": (239, 246, 255, 242),
    "mode_fill": (235, 250, 243, 242),
    "decision_fill": (255, 246, 220, 246),
    "output_fill": (242, 235, 255, 246),
    "warning_fill": (255, 240, 235, 246),
    "label_bg": (255, 255, 255, 210),
    "transparent": (255, 255, 255, 0),
}


def font(size):
    return ImageFont.truetype(str(FONT_PATH), size=size, index=0)


TITLE_FONT = font(25)
BODY_FONT = font(22)
SMALL_FONT = font(18)


def text_size(draw, text, fnt):
    box = draw.textbbox((0, 0), text, font=fnt)
    return box[2] - box[0], box[3] - box[1]


def wrap(draw, text, fnt, max_w):
    lines = []
    for para in text.split("\n"):
        current = ""
        for ch in para:
            trial = current + ch
            if not current or text_size(draw, trial, fnt)[0] <= max_w:
                current = trial
            else:
                lines.append(current)
                current = ch
        if current:
            lines.append(current)
    return lines


def centered_text(draw, x, y, w, h, text, fnt=BODY_FONT, fill=COLORS["text"], max_w_pad=28, bold=False):
    lines = wrap(draw, text, fnt, w - max_w_pad)
    line_heights = [text_size(draw, line, fnt)[1] for line in lines]
    gap = 6
    total_h = sum(line_heights) + gap * max(0, len(lines) - 1)
    cy = y + (h - total_h) / 2
    for line, lh in zip(lines, line_heights):
        tw, _ = text_size(draw, line, fnt)
        tx = x + (w - tw) / 2
        draw.text((tx, cy), line, font=fnt, fill=fill)
        if bold:
            draw.text((tx + 1, cy), line, font=fnt, fill=fill)
        cy += lh + gap


def box(draw, x, y, w, h, text, fill_key="calc_fill", fnt=BODY_FONT):
    draw.rounded_rectangle((x, y, x + w, y + h), radius=18, fill=COLORS[fill_key], outline=COLORS["line"], width=3)
    centered_text(draw, x, y, w, h, text, fnt=fnt, bold=True)
    return (x, y, w, h)


def diamond(draw, x, y, w, h, text):
    pts = [(x + w / 2, y), (x + w, y + h / 2), (x + w / 2, y + h), (x, y + h / 2)]
    draw.polygon(pts, fill=COLORS["decision_fill"], outline=COLORS["line"])
    draw.line(pts + [pts[0]], fill=COLORS["line"], width=3)
    centered_text(draw, x + w * 0.14, y + h * 0.14, w * 0.72, h * 0.72, text, fnt=SMALL_FONT, bold=True)
    return (x, y, w, h)


def pt_right(b):
    x, y, w, h = b
    return x + w, y + h / 2


def pt_left(b):
    x, y, w, h = b
    return x, y + h / 2


def pt_top(b):
    x, y, w, h = b
    return x + w / 2, y


def pt_bottom(b):
    x, y, w, h = b
    return x + w / 2, y + h


def arrow(draw, p1, p2, label=None):
    x1, y1 = p1
    x2, y2 = p2
    draw.line((x1, y1, x2, y2), fill=COLORS["line"], width=4)
    angle = math.atan2(y2 - y1, x2 - x1)
    length = 16
    spread = 0.48
    left = (x2 - length * math.cos(angle - spread), y2 - length * math.sin(angle - spread))
    right = (x2 - length * math.cos(angle + spread), y2 - length * math.sin(angle + spread))
    draw.polygon([(x2, y2), left, right], fill=COLORS["line"])
    if label:
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        tw, th = text_size(draw, label, SMALL_FONT)
        draw.rounded_rectangle((mx - tw / 2 - 8, my - th / 2 - 5, mx + tw / 2 + 8, my + th / 2 + 5), radius=8, fill=COLORS["label_bg"])
        draw.text((mx - tw / 2, my - th / 2), label, font=SMALL_FONT, fill=COLORS["title"])


def build():
    img = Image.new("RGBA", (W, H), COLORS["transparent"])
    draw = ImageDraw.Draw(img)

    # Main compact top-down chain.
    cx = W // 2
    main_w, main_h = 610, 78
    top_y, gap = 36, 20
    A = box(draw, cx - main_w / 2, top_y, main_w, main_h, "输入冷站运行数据", "input_fill")
    B = box(draw, cx - main_w / 2, top_y + 1 * (main_h + gap), main_w, main_h, "读取当前时刻运行状态", "input_fill")
    C = box(draw, cx - main_w / 2, top_y + 2 * (main_h + gap), main_w, main_h, "判断蓄冰量变化", "calc_fill")
    D = box(draw, cx - main_w / 2, top_y + 3 * (main_h + gap), main_w, main_h, "识别系统处于制冰、释冰或冰量基本不变状态", "calc_fill", SMALL_FONT)
    E = box(draw, cx - main_w / 2, top_y + 4 * (main_h + gap), main_w, main_h, "估算当前可用蓄冰能力", "calc_fill")
    F = box(draw, cx - main_w / 2, top_y + 5 * (main_h + gap), main_w, main_h, "估算当前最大可释冰能力", "calc_fill")
    G = diamond(draw, cx - 150, top_y + 6 * (main_h + gap) - 8, 300, 132, "判断当前工况")
    for first, second in [(A, B), (B, C), (C, D), (D, E), (E, F), (F, G)]:
        arrow(draw, pt_bottom(first), pt_top(second))

    # Mode branches. Kept close to the decision node to shorten arrows.
    branch_y = 760
    col_w = 390
    col_h = 70
    col_gap_y = 18
    xs = [70, 515, 960, 1405]
    chain_texts = [
        ["纯释冰 / 异常 / 未定义工况", "主冷机可削减空间较小", "通常不建议参与响应"],
        ["释冰+基载 / 释冰+基载+双工况", "增加释冰功率，进一步替代冷机", "形成额外削减能力"],
        ["基载 / 基载+双工况", "用蓄冰替代部分机械制冷", "形成冷机侧削减能力"],
        ["制冰", "停止或降低制冰", "形成短时削减能力"],
    ]
    branch_chains = []
    for x, texts in zip(xs, chain_texts):
        fills = ["mode_fill", "calc_fill", "calc_fill"]
        if "异常" in texts[0]:
            fills = ["warning_fill", "warning_fill", "warning_fill"]
        chain = []
        for i, txt in enumerate(texts):
            chain.append(box(draw, x, branch_y + i * (col_h + col_gap_y), col_w, col_h, txt, fills[i], SMALL_FONT))
            if i:
                arrow(draw, pt_bottom(chain[i - 1]), pt_top(chain[i]))
        branch_chains.append(chain)
        arrow(draw, pt_bottom(G), pt_top(chain[0]))

    # Rejoin and downstream calculation.
    L = box(draw, cx - 390, 1040, 780, 76, "将冷量侧可调能力换算为电功率侧削减能力", "calc_fill", SMALL_FONT)
    for chain in branch_chains:
        arrow(draw, pt_bottom(chain[-1]), pt_top(L))

    M = box(draw, cx - main_w / 2, 1142, main_w, main_h, "计算当前可削减功率", "calc_fill")
    N = diamond(draw, cx - 155, 1240, 310, 138, "是否存在有效削减空间？")
    arrow(draw, pt_bottom(L), pt_top(M))
    arrow(draw, pt_bottom(M), pt_top(N))

    P = box(draw, 130, 1408, 540, 94, "响应时长、可转移冷量和反弹功率\n均记为无有效响应", "warning_fill", SMALL_FONT)
    Q = box(draw, cx - main_w / 2, 1408, main_w, main_h, "估算可响应时长", "calc_fill")
    R = box(draw, cx - main_w / 2, 1506, main_w, main_h, "根据蓄冰余量、目标响应时间和当前工况判断可持续时间", "calc_fill", SMALL_FONT)
    S = box(draw, cx - main_w / 2, 1604, main_w, main_h, "估算可转移冷量", "calc_fill")
    T = box(draw, cx - main_w / 2, 1702, main_w, main_h, "估算响应后的反弹功率", "calc_fill")
    U = diamond(draw, cx - 145, 1804, 290, 132, "响应等级判断")
    arrow(draw, pt_left(N), pt_top(P), "否")
    arrow(draw, pt_bottom(N), pt_top(Q), "是")
    for first, second in [(Q, R), (R, S), (S, T), (T, U)]:
        arrow(draw, pt_bottom(first), pt_top(second))

    V = box(draw, 420, 1980, 300, 78, "可响应", "mode_fill")
    Wb = box(draw, 800, 1980, 300, 78, "谨慎响应", "decision_fill")
    X = box(draw, 1180, 1980, 300, 78, "不建议响应", "warning_fill")
    arrow(draw, pt_bottom(U), pt_top(V), "满足要求")
    arrow(draw, pt_bottom(U), pt_top(Wb), "余量有限")
    arrow(draw, pt_bottom(U), pt_top(X), "其他")

    Y = box(draw, cx - 300, 2110, 600, 76, "输出可调潜力结果", "output_fill")
    Z = box(draw, cx - 455, 2206, 910, 90, "输出内容包括：削减能力、响应时长、可转移冷量、反弹风险、可用蓄冰能力和响应等级", "output_fill", SMALL_FONT)
    for node in [P, V, Wb, X]:
        arrow(draw, pt_bottom(node), pt_top(Y))
    arrow(draw, pt_bottom(Y), pt_top(Z))

    # Trim transparent margins while preserving a little breathing room.
    bbox = img.getbbox()
    if bbox:
        pad = 28
        crop = (
            max(bbox[0] - pad, 0),
            max(bbox[1] - pad, 0),
            min(bbox[2] + pad, W),
            min(bbox[3] + pad, H),
        )
        img = img.crop(crop)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT_PATH)
    print(OUT_PATH)


if __name__ == "__main__":
    build()
