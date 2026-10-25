# -*- coding: utf-8 -*-
"""生成投稿封面图 cover.png —— 查证科技风 1280x720"""
from PIL import Image, ImageDraw, ImageFont
import os

W, H = 1280, 720
BG = (7, 11, 20)
CYAN = (0, 229, 192)
CYAN_DIM = (0, 168, 140)
BLUE = (59, 130, 246)
TXT = (232, 238, 249)
DIM = (138, 155, 181)
OK = (34, 211, 154)
BAD = (255, 77, 109)

F_BOLD = "C:/Windows/Fonts/msyhbd.ttc"
F_REG = "C:/Windows/Fonts/msyh.ttc"
F_LATIN = "C:/Windows/Fonts/consolab.ttf"

_cache = {}


def font(path, size):
    k = (path, size)
    if k not in _cache:
        _cache[k] = ImageFont.truetype(path, size)
    return _cache[k]


img = Image.new("RGB", (W, H), BG)


def glow(cx, cy, r, color, alpha_max):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    steps = 46
    for i in range(steps, 0, -1):
        rr = r * i / steps
        a = int(alpha_max * (1 - i / steps) ** 1.8)
        ld.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=color + (a,))
    base = img.convert("RGBA")
    img.paste(Image.alpha_composite(base, layer).convert("RGB"), (0, 0))


# 背景网格
d = ImageDraw.Draw(img, "RGBA")
for x in range(0, W, 40):
    d.line([(x, 0), (x, H)], fill=(255, 255, 255, 7))
for y in range(0, H, 40):
    d.line([(0, y), (W, y)], fill=(255, 255, 255, 7))

# 双色光晕
glow(150, -60, 640, CYAN, 48)
glow(1180, 70, 720, BLUE, 42)
d = ImageDraw.Draw(img, "RGBA")

# 顶部渐变条
d.rectangle([0, 0, int(W * 0.55), 3], fill=CYAN + (240,))
d.rectangle([int(W * 0.55), 0, W, 3], fill=BLUE + (200,))


def text(xy, s, f, fill, anchor="la"):
    d.text(xy, s, font=f, fill=fill, anchor=anchor)


def text_latin(xy, s, f_path, size, fill, anchor="la"):
    """只用于纯 ASCII 内容"""
    d.text(xy, s, font=font(f_path, size), fill=fill, anchor=anchor)


# ============ 左上品牌区 ============
lx, ly, ls = 88, 74, 56
d.polygon([
    (lx + ls / 2, ly), (lx + ls, ly + ls * 0.26), (lx + ls, ly + ls * 0.60),
    (lx + ls / 2, ly + ls), (lx, ly + ls * 0.60), (lx, ly + ls * 0.26),
], outline=CYAN + (255,), width=3)
d.line([(lx + 14, ly + 27), (lx + 25, ly + 39), (lx + 43, ly + 16)],
       fill=CYAN + (255,), width=4, joint="curve")

text_latin((lx + ls + 20, ly - 4), "VERITAS", F_LATIN, 25, CYAN)
text((lx + ls + 20, ly + 28), "查证引擎 · FACT CHECK", font(F_REG, 13), DIM)

# ============ 主标题 ============
text((88, 176), "查证台", font(F_BOLD, 82), TXT)
text((88, 276), "结论有依据，来源可追溯", font(F_BOLD, 38), CYAN)

# 副标题（两行）
text((90, 348), "粘贴一条网传消息 → 关键词提取 → 全网检索 → 证据双栏核对",
     font(F_REG, 19), DIM)
text((90, 380), "→ 三级可信度分级 → 查证卡生成，每条依据都可点击追溯",
     font(F_REG, 19), DIM)

# ============ 六步流程条（限宽 690） ============
steps = ["输入", "关键词", "检索", "核对", "分级", "卡片"]
sx, sy = 88, 442
bw, bh, gap = 96, 42, 22
for i, s in enumerate(steps):
    x = sx + i * (bw + gap)
    active = i in (0, 2, 5)
    fill = CYAN + (26,) if active else (255, 255, 255, 10)
    bc = CYAN + (200,) if active else (42, 61, 92, 230)
    d.rounded_rectangle([x, sy, x + bw, sy + bh], radius=8, fill=fill, outline=bc, width=1)
    text((x + bw / 2, sy + bh / 2 + 1), s, font(F_BOLD, 17),
         TXT if active else DIM, anchor="mm")
    if i < len(steps) - 1:
        ax = x + bw + 5
        d.line([(ax, sy + bh / 2), (ax + gap - 11, sy + bh / 2)],
               fill=(42, 61, 92, 255), width=2)
        tip = ax + gap - 11
        d.polygon([(tip, sy + bh / 2), (tip - 7, sy + bh / 2 - 4),
                   (tip - 7, sy + bh / 2 + 4)], fill=(42, 61, 92, 255))

# ============ 右侧查证卡 ============
cx, cy, cw, ch = 812, 96, 380, 418
d.rounded_rectangle([cx, cy, cx + cw, cy + ch], radius=16,
                    fill=(14, 21, 36, 250), outline=(42, 61, 92, 255), width=1)
d.rounded_rectangle([cx, cy + 22, cx + 3, cy + ch - 22], radius=2, fill=CYAN + (255,))

text((cx + 22, cy + 18), "查证卡", font(F_BOLD, 16), TXT)
text_latin((cx + cw - 22, cy + 21), "VC-20261024", F_LATIN, 12, DIM, anchor="ra")
d.line([(cx + 22, cy + 46), (cx + cw - 22, cy + 46)], fill=(30, 44, 68, 255), width=1)

# 结论徽章
bx, byy = cx + 22, cy + 62
d.rounded_rectangle([bx, byy, bx + 96, byy + 38], radius=8,
                    fill=BAD + (30,), outline=BAD + (170,), width=2)
text((bx + 48, byy + 19), "不 实", font(F_BOLD, 23), BAD, anchor="mm")

# 置信度
text((bx + 112, byy + 1), "置信度", font(F_REG, 11), DIM)
text_latin((bx + 112, byy + 15), "90", F_LATIN, 24, TXT)
text_latin((bx + 142, byy + 24), "%", F_LATIN, 12, DIM)

pb_x, pb_y, pb_w = bx + 112, byy + 32, 148
d.rounded_rectangle([pb_x, pb_y - 20, pb_x + pb_w, pb_y - 15], radius=2, fill=(30, 44, 68, 255))
d.rounded_rectangle([pb_x, pb_y - 20, pb_x + int(pb_w * 0.90), pb_y - 15], radius=2, fill=BAD + (230,))

d.line([(cx + 22, cy + 116), (cx + cw - 22, cy + 116)], fill=(30, 44, 68, 255), width=1)

# 卡内结论摘要（补充信息密度）
text((cx + 22, cy + 122), "现代锂电池有充电管理芯片，充满自动停充", font(F_REG, 11), DIM)

# 双栏标题
text((cx + 22, cy + 150), "支持依据", font(F_BOLD, 13), OK)
text((cx + 200, cy + 150), "矛盾证据", font(F_BOLD, 13), BAD)

rows = [
    ("锂电池充电管理机制", "cesi.cn", 0),
    ("中国消费者协会说明", "cca.org.cn", 0),
    ("整夜充电损伤电池", "网传原文", 1),
    ("电池过充会爆炸", "网传原文", 1),
]
ry = cy + 174
for title, dom, side in rows:
    col = OK if side == 0 else BAD
    rx = cx + 22 if side == 0 else cx + 200
    rw = 158
    d.rounded_rectangle([rx, ry, rx + rw, ry + 40], radius=6,
                        fill=(255, 255, 255, 9), outline=(30, 44, 68, 255), width=1)
    d.ellipse([rx + 9, ry + 14, rx + 15, ry + 20], fill=col + (255,))
    text((rx + 22, ry + 6), title, font(F_REG, 11), TXT)
    text_latin((rx + 22, ry + 24), dom, F_LATIN, 9, DIM)
    ry += 48

# 卡片底部
fy = cy + ch - 42
d.line([(cx + 22, fy - 6), (cx + cw - 22, fy - 6)], fill=(30, 44, 68, 255), width=1)
text((cx + 22, fy + 4), "来源 10 条", font(F_REG, 11), CYAN)
text((cx + 106, fy + 4), "支持 3", font(F_REG, 11), OK)
text((cx + 174, fy + 4), "矛盾 3", font(F_REG, 11), BAD)
text((cx + cw - 22, fy + 4), "融合引擎", font(F_REG, 11), DIM, anchor="ra")

# ============ 底部信息 ============
d.line([(88, 592), (W - 88, 592)], fill=(30, 44, 68, 255), width=1)
text((88, 612), "FastAPI · 八领域知识库 121 条 · 全国高校库 322 所 · 三引擎融合 · 零框架前端",
     font(F_REG, 14), DIM)
text((W - 88, 614), "AI 切磋大会 · 1024 超能 Coding 周末", font(F_REG, 12), CYAN_DIM, anchor="ra")

# 扫描线
for y in range(0, H, 3):
    if (y // 3) % 4 == 0:
        d.line([(0, y), (W, y)], fill=(255, 255, 255, 4))

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cover.png")
img.save(out, "PNG", optimize=True)
print("saved:", out, img.size, os.path.getsize(out), "bytes")
