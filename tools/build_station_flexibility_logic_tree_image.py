from pathlib import Path
import math

from PIL import Image, ImageDraw, ImageFont


OUT_PATH = Path(__file__).resolve().parents[1] / "outputs" / "冷站侧可调潜力逻辑树_描述版.png"
FONT_PATH = Path("C:/Windows/Fonts/msyh.ttc")

W, H = 1920, 1080

COLORS = {
    "bg": (255, 255, 255),
    "title": (18, 52, 86),
    "text": (24, 35, 48),
    "muted": (82, 96, 112),
    "line": (42, 83, 145),
    "input_fill": (225, 239, 255),
    "calc_fill": (239, 246, 255),
    "mode_fill": (235, 250, 243),
    "decision_fill": (255, 246, 220),
    "output_fill": (242, 235, 255),
    "warning_fill": (255, 240, 235),
}


def font(size, bold=False):
    # Microsoft YaHei TTC index 0 is regular; bold is simulated by drawing twice when needed.
    return ImageFont.truetype(str(FONT_PATH), size=size, index=0)


TITLE_FONT = font(34)
BOX_TITLE_FONT = font(19)
BOX_BODY_FONT = font(16)
SMALL_BODY_FONT = font(14)
NOTE_FONT = font(18)


def text_size(draw, text, fnt):
    box = draw.textbbox((0, 0), text, font=fnt)
    return box[2] - box[0], box[3] - box[1]


def wrap_text(draw, text, fnt, max_w):
    lines = []
    for raw_line in text.split("\n"):
        if not raw_line:
            lines.append("")
            continue
        current = ""
        for ch in raw_line:
            trial = current + ch
            if text_size(draw, trial, fnt)[0] <= max_w or not current:
                current = trial
            else:
                lines.append(current)
                current = ch
        if current:
            lines.append(current)
    return lines


def draw_centered_lines(draw, box, lines, fnt, fill, line_gap=4, bold=False):
    x, y, w, h = box
    heights = [text_size(draw, line, fnt)[1] for line in lines]
    total_h = sum(heights) + line_gap * max(0, len(lines) - 1)
    cy = y + (h - total_h) / 2
    for line, lh in zip(lines, heights):
        tw, _ = text_size(draw, line, fnt)
        tx = x + (w - tw) / 2
        if bold:
            draw.text((tx, cy), line, font=fnt, fill=fill)
            draw.text((tx + 1, cy), line, font=fnt, fill=fill)
        else:
            draw.text((tx, cy), line, font=fnt, fill=fill)
        cy += lh + line_gap


def draw_box(draw, x, y, w, h, title, body="", fill_key="calc_fill", body_font=BOX_BODY_FONT):
    r = 16
    draw.rounded_rectangle((x, y, x + w, y + h), radius=r, fill=COLORS[fill_key], outline=COLORS["line"], width=2)
    max_text_w = w - 28
    title_lines = wrap_text(draw, title, BOX_TITLE_FONT, max_text_w)
    body_lines = wrap_text(draw, body, body_font, max_text_w) if body else []

    title_h = sum(text_size(draw, line, BOX_TITLE_FONT)[1] for line in title_lines) + 4 * max(0, len(title_lines) - 1)
    body_h = sum(text_size(draw, line, body_font)[1] for line in body_lines) + 3 * max(0, len(body_lines) - 1)
    total_h = title_h + (8 if body_lines else 0) + body_h
    cy = y + (h - total_h) / 2

    for line in title_lines:
        tw, th = text_size(draw, line, BOX_TITLE_FONT)
        tx = x + (w - tw) / 2
        draw.text((tx, cy), line, font=BOX_TITLE_FONT, fill=COLORS["title"])
        draw.text((tx + 1, cy), line, font=BOX_TITLE_FONT, fill=COLORS["title"])
        cy += th + 4
    cy += 4 if body_lines else 0
    for line in body_lines:
        tw, th = text_size(draw, line, body_font)
        tx = x + (w - tw) / 2
        draw.text((tx, cy), line, font=body_font, fill=COLORS["text"])
        cy += th + 3
    return (x, y, w, h)


def draw_diamond(draw, x, y, w, h, title, body=""):
    pts = [(x + w / 2, y), (x + w, y + h / 2), (x + w / 2, y + h), (x, y + h / 2)]
    draw.polygon(pts, fill=COLORS["decision_fill"], outline=COLORS["line"])
    draw.line(pts + [pts[0]], fill=COLORS["line"], width=2)
    lines = wrap_text(draw, title + (("\n" + body) if body else ""), SMALL_BODY_FONT, w * 0.68)
    draw_centered_lines(draw, (x + w * 0.16, y + h * 0.12, w * 0.68, h * 0.76), lines, SMALL_BODY_FONT, COLORS["title"], bold=True)
    return (x, y, w, h)


def arrow(draw, p1, p2, label=None):
    x1, y1 = p1
    x2, y2 = p2
    draw.line((x1, y1, x2, y2), fill=COLORS["line"], width=3)
    angle = math.atan2(y2 - y1, x2 - x1)
    length = 14
    spread = 0.46
    p_left = (x2 - length * math.cos(angle - spread), y2 - length * math.sin(angle - spread))
    p_right = (x2 - length * math.cos(angle + spread), y2 - length * math.sin(angle + spread))
    draw.polygon([(x2, y2), p_left, p_right], fill=COLORS["line"])
    if label:
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        tw, th = text_size(draw, label, SMALL_BODY_FONT)
        draw.rounded_rectangle((mx - tw / 2 - 6, my - th / 2 - 3, mx + tw / 2 + 6, my + th / 2 + 3), radius=5, fill=COLORS["bg"])
        draw.text((mx - tw / 2, my - th / 2), label, font=SMALL_BODY_FONT, fill=COLORS["muted"])


def right(box):
    x, y, w, h = box
    return x + w, y + h / 2


def left(box):
    x, y, w, h = box
    return x, y + h / 2


def top(box):
    x, y, w, h = box
    return x + w / 2, y


def bottom(box):
    x, y, w, h = box
    return x + w / 2, y + h


def build():
    img = Image.new("RGB", (W, H), COLORS["bg"])
    draw = ImageDraw.Draw(img)

    title = "冷站侧可调潜力快速估算逻辑树（前期阶段）"
    tw, th = text_size(draw, title, TITLE_FONT)
    draw.text(((W - tw) / 2, 26), title, font=TITLE_FONT, fill=COLORS["title"])
    draw.text(((W - tw) / 2 + 1, 26), title, font=TITLE_FONT, fill=COLORS["title"])

    y1, h1 = 94, 154
    w1, gap1, x0 = 280, 25, 46
    row1_data = [
        ("1 输入冷站运行数据", "导入冷站历史运行记录\n作为快速估算的数据基础"),
        ("2 读取当前时刻数据", "读取功率、冷负荷、蓄冰量\n以及当前运行工况"),
        ("3 判断冰量变化", "比较当前与上一时刻蓄冰量\n识别冰量上升或下降"),
        ("4 识别制冰/释冰强度", "由冰量变化判断系统正在\n制冰、释冰或基本不变"),
        ("5 估算可用蓄冰冷量", "扣除安全余量后\n得到可参与响应的蓄冰能力"),
        ("6 估算最大释冰能力", "结合目标响应时长和历史运行能力\n确定可用释冰上限"),
    ]
    row1 = [draw_box(draw, x0 + i * (w1 + gap1), y1, w1, h1, t, b, "input_fill") for i, (t, b) in enumerate(row1_data)]
    for a, b in zip(row1, row1[1:]):
        arrow(draw, right(a), left(b))

    y2, h2 = 302, 166
    mode_w, mode_gap = 368, 27
    modes = [
        ("11 纯释冰 / 异常 / 未定义", "主冷机可削减空间较小\n通常不建议参与削减响应", "warning_fill"),
        ("10 释冰+基载 / 释冰+基载+双工况", "在已有释冰基础上增加释冰强度\n进一步替代机械制冷", "mode_fill"),
        ("9 基载 / 基载+双工况", "优先利用蓄冰替代部分机械制冷\n形成可削减电功率", "mode_fill"),
        ("8 制冰", "通过停止或降低制冰功率\n获得短时削减能力", "mode_fill"),
    ]
    mode_boxes = [draw_box(draw, 46 + i * (mode_w + mode_gap), y2, mode_w, h2, t, b, f, SMALL_BODY_FONT) for i, (t, b, f) in enumerate(modes)]
    decision = draw_diamond(draw, 1610, 292, 220, 186, "7 判断\n当前工况", "按识别规则\n进入对应分支")
    arrow(draw, bottom(row1[-1]), top(decision))
    for m in mode_boxes:
        arrow(draw, left(decision), top(m))

    y3, h3 = 526, 146
    r3 = [
        draw_box(draw, 60, y3, 275, h3, "12 冷量转为电功率", "根据制冰或机械制冷效率\n将可转移冷量折算为电功率", "calc_fill", SMALL_BODY_FONT),
        draw_box(draw, 370, y3, 252, h3, "13 得到当前削减能力", "综合停止制冰和蓄冰替代冷机\n得到当前可削减功率", "calc_fill", SMALL_BODY_FONT),
        draw_diamond(draw, 668, y3 - 6, 170, 158, "14 是否存在\n可削减功率"),
        draw_box(draw, 882, y3, 246, h3, "15 否", "当前时段不具备有效削减空间\n响应等级记为不建议响应", "warning_fill", SMALL_BODY_FONT),
        draw_box(draw, 1174, y3, 310, h3, "16 是：估算响应时长", "根据蓄冰余量、目标时长\n和当前工况估算可持续时间", "calc_fill", SMALL_BODY_FONT),
        draw_box(draw, 1525, y3, 330, h3, "17 估算可转移冷量", "统计响应期间可由蓄冰承担\n或由制冰停止释放的冷量", "calc_fill", SMALL_BODY_FONT),
    ]
    for m in mode_boxes:
        arrow(draw, bottom(m), top(r3[0]))
    for a, b in zip(r3, r3[1:]):
        arrow(draw, right(a), left(b))
    arrow(draw, right(r3[2]), left(r3[3]), "否")
    arrow(draw, right(r3[2]), left(r3[4]), "是")

    y4, h4 = 764, 166
    rebound = draw_box(draw, 1525, y4, 330, h4, "18 估算反弹功率", "考虑响应后需要补回的制冰量\n评估后续反弹风险", "calc_fill", SMALL_BODY_FONT)
    level_decision = draw_diamond(draw, 1300, y4 - 4, 178, 174, "19 响应等级\n判断")
    level_ok = draw_box(draw, 1070, y4, 180, h4, "20 可响应", "削减能力和持续时间\n均满足响应要求", "mode_fill", SMALL_BODY_FONT)
    level_mid = draw_box(draw, 855, y4, 180, h4, "21 有限响应", "具备一定削减能力\n但持续性或余量有限", "decision_fill", SMALL_BODY_FONT)
    level_no = draw_box(draw, 640, y4, 180, h4, "22 其他", "不建议响应", "warning_fill", SMALL_BODY_FONT)
    output = draw_box(
        draw,
        46,
        y4,
        545,
        h4,
        "23 输出可调潜力指标",
        "输出削减能力、响应时长、可转移冷量\n反弹风险、可用蓄冰能力\n以及最终响应等级",
        "output_fill",
        SMALL_BODY_FONT,
    )
    arrow(draw, bottom(r3[-1]), top(rebound))
    arrow(draw, left(rebound), right(level_decision))
    arrow(draw, left(level_decision), right(level_ok))
    arrow(draw, left(level_decision), right(level_mid))
    arrow(draw, left(level_decision), right(level_no))
    arrow(draw, left(level_no), right(output))

    note = "说明：本图用于展示冷站侧快速估算的逻辑关系；具体公式、阈值和默认参数保留在项目代码模块中，便于后续统一维护。"
    tw, th = text_size(draw, note, NOTE_FONT)
    draw.text(((W - tw) / 2, 1000), note, font=NOTE_FONT, fill=COLORS["muted"])

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT_PATH, quality=95)
    print(OUT_PATH)


if __name__ == "__main__":
    build()
