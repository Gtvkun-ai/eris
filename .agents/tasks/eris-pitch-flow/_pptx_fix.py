# -*- coding: utf-8 -*-
"""Sửa SLIDETHUYETTRINH.pptx: điền 4 slide trống (9,11,12,14), sửa 'Cogntion',
bỏ 'Hoa Kỳ'. Giữ 14 slide. Lưu ra file mới _FIXED."""
import copy
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE

SRC = r"C:\Users\Gtvkun\Downloads\eris research\SLIDETHUYETTRINH.pptx"
OUT = r"C:\Users\Gtvkun\Downloads\eris research\SLIDETHUYETTRINH_FIXED.pptx"

# Bảng màu theo deck (pastel fill + chữ đậm)
NAVY   = RGBColor(0x1E, 0x29, 0x3B)   # chữ tiêu đề / số
PURPLE = RGBColor(0x7C, 0x5C, 0xD6)
TEAL   = RGBColor(0x17, 0xA2, 0x8A)
BLUE   = RGBColor(0x4A, 0x6F, 0xA5)
ROSE   = RGBColor(0xC0, 0x5B, 0x6E)
GREY   = RGBColor(0x6B, 0x72, 0x80)
WHITE  = RGBColor(0xFF, 0xFF, 0xFF)

FILL_PURPLE = RGBColor(0xEC, 0xE8, 0xFA)
FILL_TEAL   = RGBColor(0xE2, 0xF5, 0xF0)
FILL_BLUE   = RGBColor(0xE6, 0xEF, 0xFA)
FILL_ROSE   = RGBColor(0xFB, 0xEA, 0xED)
FILL_LILAC  = RGBColor(0xF0, 0xED, 0xFB)
BORDER      = RGBColor(0xDD, 0xDD, 0xE5)

prs = Presentation(SRC)
slides = prs.slides

def card(slide, x, y, w, h, fill, line=BORDER, radius=True):
    shp = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE,
        Inches(x), Inches(y), Inches(w), Inches(h))
    shp.fill.solid(); shp.fill.fore_color.rgb = fill
    shp.line.color.rgb = line; shp.line.width = Pt(1)
    shp.shadow.inherit = False
    return shp

def txt(slide, x, y, w, h, text, size, color, bold=False,
        align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, font="Arial"):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame; tf.word_wrap = True
    tf.vertical_anchor = anchor
    lines = text.split("\n")
    for i, ln in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        r = p.add_run(); r.text = ln
        r.font.size = Pt(size); r.font.bold = bold
        r.font.color.rgb = color; r.font.name = font
    return tb

# ---------- SLIDE 1: sửa chính tả + màu tiêu đề về navy ----------
s1 = slides[0]
for sh in s1.shapes:
    if sh.has_text_frame:
        for p in sh.text_frame.paragraphs:
            for r in p.runs:
                if "Cogntion" in r.text:
                    r.text = r.text.replace("Cogntion", "Cognition")
                # đổi màu tiêu đề xanh lá -> navy cho khớp hệ màu
                if "ERIS" in r.text and "Cognition" in r.text:
                    r.font.color.rgb = NAVY

# ---------- SLIDE 2: bỏ 'Hoa Kỳ' ----------
s2 = slides[1]
for sh in s2.shapes:
    if sh.has_text_frame:
        for p in sh.text_frame.paragraphs:
            for r in p.runs:
                if "Hoa K" in r.text:
                    r.text = r.text.replace(", Hoa Kỳ", "").replace("ở Tennessee", "cấp hai, Tennessee")

# ============ SLIDE 9: storyboard cảnh "em hiểu rồi" ============
s9 = slides[8]
# xóa khung rỗng + ô tròn placeholder (Shape 7, Shape 8)
for sh in list(s9.shapes):
    if sh.name in ("Shape 7", "Shape 8"):
        sh._element.getparent().remove(sh._element)

# 4 khung hội thoại storyboard
bubbles = [
    ("NGƯỜI HỌC", "\u201cEm hi\u1ec3u r\u1ed3i, cho em ch\u01a1i game nha?\u201d", FILL_BLUE, BLUE),
    ("ERIS", "\u201c\u0110\u01b0\u1ee3c th\u00f4i~ nh\u01b0ng th\u1eed m\u1ed9t c\u00e2u bi\u1ebfn th\u1ec3 tr\u01b0\u1edbc \u0111\u00e3, cho ch\u1ecb y\u00ean t\u00e2m.\u201d", FILL_PURPLE, PURPLE),
    ("NG\u01af\u1edcI H\u1eccC", "(l\u00e0m sai c\u00e2u bi\u1ebfn th\u1ec3)", FILL_ROSE, ROSE),
    ("ERIS", "\u201cKh\u00f4ng sao~ ch\u1ed7 n\u00e0y d\u1ec5 nh\u1ea7m. \u0110\u1ec3 ch\u1ecb gi\u1ea3i th\u00edch c\u00e1ch kh\u00e1c, mai m\u00ecnh ki\u1ec3m l\u1ea1i nh\u00e9.\u201d", FILL_TEAL, TEAL),
]
y = 2.3
for i, (who, line, fill, accent) in enumerate(bubbles):
    c = card(s9, 0.8, y, 11.7, 0.95, fill)
    txt(s9, 1.1, y+0.12, 2.4, 0.7, who, 12, accent, bold=True, anchor=MSO_ANCHOR.MIDDLE)
    txt(s9, 3.5, y+0.12, 8.7, 0.7, line, 16, NAVY, bold=True, anchor=MSO_ANCHOR.MIDDLE)
    y += 1.08
# dải dưới: mạch cơ chế
flow = card(s9, 0.8, 6.75, 11.7, 0.55, FILL_LILAC)
txt(s9, 0.8, 6.80, 11.7, 0.45,
    "Root \u2192 Tutor c\u1eadp nh\u1eadt gi\u1ea3 thuy\u1ebft \u2192 \u0111\u1ed5i c\u00e1ch d\u1ea1y \u2192 ghi \u0111i\u1ec3m c\u1ea7n \u00f4n: m\u1ed9t k\u1ebft qu\u1ea3 h\u00f4m nay \u0111\u1ed5i quy\u1ebft \u0111\u1ecbnh ng\u00e0y mai.",
    13, NAVY, bold=True, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)

# ============ SLIDE 11: khả thi — 3 cột + HOTFIX ============
s11 = slides[10]
for sh in list(s11.shapes):
    if sh.name in ("Shape 6", "Shape 7", "Text 8", "Text 9", "Shape 10"):
        sh._element.getparent().remove(sh._element)

cols = [
    ("\u0110\u00c3 C\u00d3 N\u1ec0N", TEAL, FILL_TEAL, [
        "Root loop + capability", "Context + continuation",
        "Learning: path, evidence,", "mastery, review", "TTS / Live2D"]),
    ("MVP KI\u1ec2M CH\u1ee8NG", PURPLE, FILL_PURPLE, [
        "M\u1ed9t phi\u00ean h\u1ecdc tr\u1ecdn:", "\u0111\u1eb7t b\u00e0i \u2192 evidence \u2192",
        "receipt \u2192 resume", "M\u1ed9t m\u00f4n, m\u1ed9t nh\u00f3m", "\u0111o mastery theo th\u1eddi gian"]),
    ("M\u1ede R\u1ed8NG", BLUE, FILL_BLUE, [
        "Nhi\u1ec1u m\u00f4n, t\u00e0i li\u1ec7u", "\u1ea2nh b\u00e0i l\u00e0m (vision)",
        "Nh\u1eafc h\u1ecdc nhi\u1ec1u ng\u00e0y", "D\u1ef1 \u0111o\u00e1n \u0111i\u1ec3m y\u1ebfu", ""]),
]
x = 0.7
for title, accent, fill, items in cols:
    card(s11, x, 2.2, 3.85, 2.9, fill)
    txt(s11, x+0.2, 2.35, 3.5, 0.5, title, 15, accent, bold=True, align=PP_ALIGN.CENTER)
    body = "\n".join("\u2022 " + it if it else "" for it in items)
    txt(s11, x+0.25, 2.95, 3.35, 2.0, body, 12, NAVY)
    x += 4.07
# mũi tên giữa các cột
for ax in (4.45, 8.52):
    a = txt(s11, ax, 3.4, 0.3, 0.5, "\u2192", 20, GREY, bold=True, align=PP_ALIGN.CENTER)
# dải HOTFIX (vết sẹo thật)
card(s11, 0.7, 5.35, 11.82, 1.35, RGBColor(0x1E,0x29,0x3B), line=NAVY)
txt(s11, 1.0, 5.45, 11.2, 0.4,
    "M\u1ed8T V\u1ebeT S\u1eb8O TH\u1eacT",
    12, RGBColor(0xF5,0xC8,0x6B), bold=True)
txt(s11, 1.0, 5.80, 11.2, 0.85,
    "B\u01b0\u1edbc ki\u1ec3m b\u1eaft bu\u1ed9c tr\u01b0\u1edbc khi n\u00f3i t\u1eebng b\u1ecb x\u1ebfp nh\u1ea7m v\u00e0o nh\u00f3m \u201c\u0111\u01b0\u1ee3c b\u1ecf khi m\u00e1y b\u1eadn\u201d \u2192 Eris im gi\u1eefa bu\u1ed5i. "
    "G\u1ed1c: ph\u00e2n lo\u1ea1i theo nh\u00e3n c\u0169. Lu\u1eadt kh\u00f4ng bao gi\u1edd ph\u00e1: VAI TR\u00d2 X\u00c9T TR\u01af\u1edaC NH\u00c3N.",
    13, WHITE)

# ============ SLIDE 12: tác động — 4 chỉ số ============
s12 = slides[11]
for sh in list(s12.shapes):
    if sh.name in ("Shape 7", "Shape 8"):
        sh._element.getparent().remove(sh._element)

metrics = [
    ("Ti\u1ebfn b\u1ed9 ki\u1ebfn th\u1ee9c", "b\u00e0i tr\u01b0\u1edbc\u2013sau, b\u00e0i bi\u1ebfn th\u1ec3", PURPLE, FILL_PURPLE),
    ("Quay l\u1ea1i h\u1ecdc", "c\u00f3 m\u1ee5c ti\u00eau, kh\u00f4ng ph\u1ea3i s\u1ed1 ph\u00fat chat", TEAL, FILL_TEAL),
    ("Ph\u1ee5 thu\u1ed9c g\u1ee3i \u00fd", "gi\u1ea3m d\u1ea7n = h\u1ecdc th\u1eadt", BLUE, FILL_BLUE),
    ("Chi ph\u00ed m\u1ed7i phi\u00ean", "gi\u00e1 tr\u1ecb ph\u1ea3i b\u00f9 \u0111\u01b0\u1ee3c chi ph\u00ed", ROSE, FILL_ROSE),
]
xs = [0.7, 3.72, 6.74, 9.76]
for (title, sub, accent, fill), x in zip(metrics, xs):
    card(s12, x, 2.4, 2.8, 2.3, fill)
    txt(s12, x+0.2, 2.7, 2.4, 0.3, f"{xs.index(x)+1:02d}", 22, accent, bold=True)
    txt(s12, x+0.2, 3.25, 2.4, 0.8, title, 15, NAVY, bold=True)
    txt(s12, x+0.2, 4.0, 2.45, 0.6, sub, 11, GREY)
card(s12, 0.7, 5.1, 11.82, 0.95, FILL_LILAC)
txt(s12, 1.0, 5.2, 11.2, 0.75,
    "N\u1ebfu tr\u00f2 chuy\u1ec7n nhi\u1ec1u h\u01a1n m\u00e0 ki\u1ebfn th\u1ee9c kh\u00f4ng t\u1ed1t h\u01a1n, Eris v\u1eabn ch\u01b0a \u0111\u1ea1t m\u1ee5c ti\u00eau. "
    "Kh\u00e1c bi\u1ec7t: Eris \u0111\u1ec3 l\u1ea1i d\u1eef li\u1ec7u \u0111\u1ec3 TR\u1ea2 L\u1edcI c\u00e2u h\u1ecfi n\u00e0y \u2014 chatbot th\u01b0\u1eddng th\u00ec kh\u00f4ng.",
    13, NAVY, bold=True, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)

# ============ SLIDE 14: CHỐT / tuyên ngôn ============
s14 = slides[13]
txt(s14, 1.2, 2.3, 8.0, 1.8,
    "Model r\u1ed3i s\u1ebd thay.\nTh\u1ee9 \u1edf l\u1ea1i l\u00e0 m\u1ed9t c\u00e1ch \u0111\u1ed3ng h\u00e0nh bi\u1ebft quan s\u00e1t, bi\u1ebft ki\u1ec3m tra, v\u00e0 bi\u1ebft quay l\u1ea1i \u0111\u00fang l\u00fac.",
    30, NAVY, bold=True)
txt(s14, 1.2, 4.5, 8.5, 0.6,
    "ERIS \u2014 M\u1ed9t nh\u00e2n v\u1eadt \u0111\u1ec3 g\u1eafn b\u00f3. M\u1ed9t h\u1ec7 th\u1ed1ng \u0111\u1ec3 ti\u1ebfn b\u1ed9.",
    18, PURPLE, bold=True)
txt(s14, 1.2, 5.35, 9.0, 0.5,
    "C\u00e1c nh\u00f3m kh\u00e1c x\u00e2y m\u1ed9t c\u00e2u tr\u1ea3 l\u1eddi. Ch\u00fang em x\u00e2y m\u1ed9t c\u00e1ch ngh\u0129.",
    15, GREY)
txt(s14, 1.2, 6.9, 8.0, 0.3, "Em c\u1ea3m \u01a1n ban gi\u00e1m kh\u1ea3o.", 12, GREY)

prs.save(OUT)
print("SAVED:", OUT)
print("slides:", len(prs.slides))
