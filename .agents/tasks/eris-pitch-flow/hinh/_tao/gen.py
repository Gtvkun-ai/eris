import html
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent
W, H = 1280, 720
INK = '#e9f3f1'; DIM = '#8fb0ab'; MINT = '#5fd6c4'; AMB = '#f2b353'
ROSE = '#e8849a'; BLUE = '#7aa7ff'; VIO = '#b79cff'
CARD = '#102a36'; LINE = '#1d3a44'; CODE = '#0a161c'; MINTBG = '#0f3a3d'
FONT = "'Segoe UI','Noto Sans',Arial,sans-serif"
MONO = "'Cascadia Code',Consolas,'Courier New',monospace"
MARK_COLORS = [MINT, ROSE, AMB, DIM, BLUE, VIO]


def esc(s):
    return html.escape(str(s), quote=False)


class S:
    def __init__(self, num, kicker, title, tsize=38, sub=None):
        self.num = num
        self.o = []
        self.rect(0, 0, W, 6, fill=MINT, rx=0)
        self.text(56, 50, kicker, size=14, fill=MINT, weight=700, ls=2)
        self.text(56, 98, title, size=tsize, weight=800)
        if sub:
            self.text(56, 138, sub, size=18, fill=DIM)
        self.rect(56, 672, 1168, 1, fill=LINE, rx=0)
        self.text(56, 698, "ERIS · GIA SƯ AI ĐỒNG HÀNH", size=12, fill='#5c7b78', weight=700, ls=1)
        self.text(1224, 698, f"{num:02d}", size=12, fill='#5c7b78', weight=700, anchor='end')

    def rect(self, x, y, w, h, fill='none', stroke=None, sw=1.5, rx=14, dash=None, op=1):
        st = stroke if stroke else 'none'
        d = f' stroke-dasharray="{dash}"' if dash else ''
        self.o.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{st}" stroke-width="{sw}"{d} opacity="{op}"/>')

    def circle(self, cx, cy, r, fill='none', stroke=None, sw=2):
        st = stroke if stroke else 'none'
        self.o.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{fill}" stroke="{st}" stroke-width="{sw}"/>')

    def text(self, x, y, txt, size=18, fill=INK, weight=400, anchor='start', mono=False, ls=0, op=1):
        fam = MONO if mono else FONT
        if isinstance(txt, str):
            inner = esc(txt)
        else:
            parts = []
            for t in txt:
                w = t[2] if len(t) > 2 else weight
                parts.append(f'<tspan fill="{t[1]}" font-weight="{w}">{esc(t[0])}</tspan>')
            inner = ''.join(parts)
        l = f' letter-spacing="{ls}"' if ls else ''
        self.o.append(f'<text x="{x}" y="{y}" font-family="{fam}" font-size="{size}" font-weight="{weight}" fill="{fill}" text-anchor="{anchor}" opacity="{op}"{l} xml:space="preserve">{inner}</text>')

    def path(self, d, color=MINT, sw=3, dash=None, head=True, tail=False):
        mid = 'm' + color[1:]
        a = f' marker-end="url(#{mid})"' if head else ''
        b = f' marker-start="url(#{mid})"' if tail else ''
        da = f' stroke-dasharray="{dash}"' if dash else ''
        self.o.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{sw}" stroke-linecap="round" stroke-linejoin="round"{da}{a}{b}/>')

    def line(self, x1, y1, x2, y2, **k):
        self.path(f"M{x1},{y1} L{x2},{y2}", **k)

    def pill(self, x, y, w, h, label, fill, stroke, tc, size=13, weight=700, mono=False):
        self.rect(x, y, w, h, fill, stroke, 1.5, rx=h / 2)
        self.text(x + w / 2, y + h / 2 + size * 0.35, label, size=size, fill=tc, weight=weight, anchor='middle', mono=mono)

    def codebox(self, x, y, w, h, lines, size=13, file=None):
        self.rect(x, y, w, h, CODE, '#16343f', 1.2, rx=10)
        self.rect(x, y + 6, 3, h - 12, MINT, None, 0, rx=1.5)
        yy = y + 24
        for ln in lines:
            self.text(x + 18, yy, ln, size=size, fill='#bfe3dd', mono=True)
            yy += size + 9
        if file:
            self.text(x + w - 14, y + h - 10, file, size=11, fill='#4e6d69', anchor='end', mono=True)

    def save(self, name):
        defs = ''.join(
            f'<marker id="m{c[1:]}" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="11" markerHeight="11" '
            f'markerUnits="userSpaceOnUse" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{c}"/></marker>'
            for c in MARK_COLORS)
        defs += '<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#0b1f2a"/><stop offset="0.6" stop-color="#0e2733"/><stop offset="1" stop-color="#0c2029"/></linearGradient>'
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">'
               f'<defs>{defs}</defs><rect width="{W}" height="{H}" fill="url(#bg)"/>' + ''.join(self.o) + '</svg>')
        (OUT / name).write_text(svg, encoding='utf-8')


# ---------------------------------------------------------------- slide 04
def s04():
    s = S(4, "LUỒNG CHẠY · MỘT LƯỢT NÓI", [("Một câu nói đi qua 7 trạm. ", INK), ("Chỉ một cửa ra.", MINT)])
    nodes = [("01", "NGÕ VÀO", "chat · giọng nói", "phân loại ngắt lời", "code", ""),
             ("02", "KERNEL", "generation + 1", "ghép ngữ cảnh", "code", "A"),
             ("03", "ROOT", "quyết từng bước", "không viết câu", "model", "AB"),
             ("04", "WRITER", "chữ Việt", "giọng Nhật", "model", "B"),
             ("05", "KIỂM CUỐI", "còn đúng lượt?", "sai → hủy", "code", ""),
             ("06", "CỬA PHÁT", "TTS · Live2D", "phụ đề", "door", ""),
             ("07", "BIÊN NHẬN", "phát xong?", "về Root · Tutor", "code", "A")]
    w, g, x0, y, h = 146, 24, 57, 176, 140
    bcol = {'A': MINT, 'B': BLUE, 'C': VIO}
    cx = []
    for i, (no, name, l1, l2, kind, bd) in enumerate(nodes):
        x = x0 + i * (w + g)
        cx.append(x + w / 2)
        if kind == 'model':
            fill, stroke, sw = MINTBG, MINT, 2.5
        elif kind == 'door':
            fill, stroke, sw = '#3a2e14', AMB, 2.5
        else:
            fill, stroke, sw = CARD, LINE, 1.5
        s.rect(x, y, w, h, fill, stroke, sw)
        s.text(x + 14, y + 26, no, size=13, fill=AMB if kind == 'door' else MINT, weight=800)
        s.text(x + 14, y + 55, name, size=20, weight=800)
        s.text(x + 14, y + 81, l1, size=14.5, fill=DIM)
        s.text(x + 14, y + 100, l2, size=14.5, fill=DIM)
        if kind == 'model':
            s.pill(x + 10, y + 110, w - 20, 22, "model · bắt buộc", MINT, None, '#06231f', 12)
        elif kind == 'door':
            s.pill(x + 10, y + 110, w - 20, 22, "cửa DUY NHẤT", AMB, None, '#2b1d02', 12)
        else:
            s.pill(x + 10, y + 110, w - 20, 22, "code thuần", '#183541', None, DIM, 12)
        for k, ch in enumerate(bd):
            bx = x + w - 2 - k * 30
            s.circle(bx, y, 13, bcol[ch])
            s.text(bx, y + 5, ch, size=14, fill='#06231f', weight=800, anchor='middle')
        if i < 6:
            s.line(x + w + 3, y + 70, x + w + g - 3, y + 70, color=MINT, sw=2.5)
    top = 146
    s.path(f"M{cx[6]},{y-4} L{cx[6]},{top} L{cx[2]+12},{top} L{cx[2]+12},{y-5}", color=MINT, sw=2.5)
    s.text((cx[6] + cx[2] + 12) / 2, top - 8, "biên nhận quay về Root", size=14, fill=MINT, anchor='middle', weight=600)
    s.path(f"M{cx[2]-30},{y-4} L{cx[2]-30},{top} L{cx[1]},{top} L{cx[1]},{y-5}", color=DIM, sw=2, dash="6 5")
    s.text((cx[1] + cx[2] - 30) / 2, top - 8, "nói tiếp", size=13, fill=DIM, anchor='middle')

    # Gia su
    tx, ty, tw, th = cx[2] - 110, 372, 220, 84
    s.rect(tx, ty, tw, th, MINTBG, VIO, 2.5)
    s.text(tx + 16, ty + 34, "GIA SƯ", size=21, weight=800)
    s.text(tx + 16, ty + 60, "learning kernel", size=15, fill=DIM)
    for k, ch in enumerate("BC"):
        bx = tx + tw - 2 - k * 30
        s.circle(bx, ty, 13, bcol[ch])
        s.text(bx, ty + 5, ch, size=14, fill='#06231f', weight=800, anchor='middle')
    s.line(cx[2] - 20, y + h + 3, cx[2] - 20, ty - 3, color=MINT, sw=2.5)
    s.line(cx[2] + 20, ty - 3, cx[2] + 20, y + h + 3, color=VIO, sw=2.5)
    s.text(cx[2] - 30, 350, "gọi", size=13, fill=MINT, anchor='end')
    s.text(cx[2] + 30, 350, "đề xuất + biên nhận", size=13, fill=VIO)

    # fail-soft
    s.rect(700, 372, 524, 84, '#2a2210', AMB, 2, dash="7 5")
    s.text(722, 398, "FAIL-SOFT · khi model lỗi", size=14, fill=AMB, weight=800)
    s.text(722, 422, "Root hoặc Writer lỗi provider (lượt của người học)", size=15)
    s.text(722, 444, "→ câu báo cố định VI + JA, không qua LLM → cửa phát", size=15)
    s.line(cx[5], 372, cx[5], y + h + 3, color=AMB, sw=2.5, dash="6 5")

    # legend
    for i, (c, t) in enumerate([(MINT, "model, làn bắt buộc"), ('#2c5160', "code thuần, không gọi model"), (AMB, "cửa phát duy nhất")]):
        s.rect(56, 384 + i * 26, 22, 14, c, None, 0, rx=7)
        s.text(88, 396 + i * 26, t, size=14, fill=DIM)

    cards = [("A", MINT, "VÒNG NHẬN THỨC CÓ KIỂM SOÁT",
              ["Chống NÓI ĐÈ: generation + 1", "Chống NÓI DỐI: có biên nhận mới tính", "Phanh: 12 bước · 2 bước không tiến triển"]),
             ("B", BLUE, "HỆ THẦN KINH NHẬN THỨC",
              ["Chống IM LẶNG", "Mỗi lời gọi model xếp làn theo vai trò", "Làn bắt buộc không bị cắt khi máy bận"]),
             ("C", VIO, "LEARNING KERNEL",
              ["Chống NÓI DỐI trong hồ sơ học", "Model đề xuất, kernel chốt (≥ 0,68)", "Writer không bao giờ cầm đáp án"])]
    for i, (ch, col, ttl, lines) in enumerate(cards):
        x = 56 + i * 396
        s.rect(x, 486, 376, 160, CARD, col, 2)
        s.circle(x + 34, 524, 18, col)
        s.text(x + 34, 530, ch, size=19, fill='#06231f', weight=800, anchor='middle')
        s.text(x + 62, 530, ttl, size=16, fill=col, weight=800)
        s.text(x + 22, 574, lines[0], size=16, fill=INK, weight=700)
        s.text(x + 22, 603, lines[1], size=15, fill=DIM)
        s.text(x + 22, 630, lines[2], size=15, fill=DIM)
    s.save("s04-luong-tong.svg")


# ---------------------------------------------------------------- slide 05
def s05():
    s = S(5, "A · VÒNG NHẬN THỨC CÓ KIỂM SOÁT",
          [("Root không trả lời. ", INK), ("Root quyết định, từng bước một.", MINT)], tsize=34,
          sub="Mỗi bước: gọi một việc → nhận kết quả kèm biên nhận → rồi mới sang bước kế.")
    ox, oy, r = 340, 362, 60
    s.rect(140, 188, 400, 40, '#0f2a33', MINT, 1.8, rx=20, dash="6 4")
    s.text(340, 214, "Trước mỗi bước: lượt này còn hiệu lực?", size=15, fill=MINT, anchor='middle', weight=600)
    s.text(552, 213, "không → NoReply", size=14, fill=ROSE, weight=600)
    s.line(340, 230, 340, 300, color=MINT, sw=2.5)
    s.circle(ox, oy, r, MINTBG, MINT, 3)
    s.text(ox, 360, "BƯỚC k", size=24, weight=800, anchor='middle')
    s.text(ox, 384, "1 hành động", size=14, fill=DIM, anchor='middle')
    chips = [(60, 256, "NHỚ LẠI", "recall_memory", (262, 298), (292, 324)),
             (420, 256, "GỌI GIA SƯ", "use_capability", (418, 298), (388, 324)),
             (60, 402, "NGHĨ THÊM", "tối đa 2 lần · không phát lời", (262, 426), (292, 400)),
             (420, 402, "GHI CHÚ", "set_note", (418, 426), (388, 400))]
    for (x, y, nm, sb, a, b) in chips:
        s.rect(x, y, 200, 64, CARD, LINE, 1.5)
        s.text(x + 100, y + 28, nm, size=19, weight=800, anchor='middle')
        s.text(x + 100, y + 50, sb, size=13, fill=DIM, anchor='middle', mono=True)
        s.line(a[0], a[1], b[0], b[1], color=MINT, sw=2.2, tail=True)
    s.line(ox, 424, ox, 496, color=MINT, sw=2.5)
    s.rect(150, 498, 380, 66, MINTBG, MINT, 2.5)
    s.text(340, 528, "CHỐT: move  hoặc  no_reply", size=19, weight=800, anchor='middle')
    s.text(340, 551, "intent · say · delivery · after  →  Writer", size=13, fill=DIM, anchor='middle')
    s.text(60, 596, "Chỉ move và no_reply đi xuống Writer.", size=15, fill=DIM)
    s.text(60, 620, "Nhớ lại, nghĩ thêm, ghi chú không bao giờ thành lời nói.", size=15, fill=DIM)

    s.text(760, 182, "BA PHANH", size=14, fill=MINT, weight=800, ls=2)
    brakes = [("12", MINT, "bước tối đa", "trần cứng: mặc định 8, tối thiểu 2"),
              ("2", AMB, "bước liền không tiến triển → dừng", "trùng · rỗng · lỗi · hết hạn mức"),
              ("2", ROSE, "lần nghĩ thầm tối đa", "continue_thinking, không phát lời")]
    for i, (n, col, l1, l2) in enumerate(brakes):
        y = 196 + i * 112
        s.rect(760, y, 464, 100, CARD, LINE, 1.5)
        s.text(790, y + 74, n, size=64, fill=col, weight=800)
        s.text(870, y + 44, l1, size=18, weight=700)
        s.text(870, y + 70, l2, size=14, fill=DIM)
    s.codebox(760, 540, 464, 104, ["max_root_steps = max(2, min(12, int(max_root_steps or 8)))", "stop = streak >= 2"], size=12, file="conversation/agent.py")
    s.save("s05-root-loop.svg")


# ---------------------------------------------------------------- slide 06
def s06():
    s = S(6, "A · CHỐNG NÓI ĐÈ", [("Bạn chen lời → ", INK), ("cả lượt cũ chết tức thì.", MINT)],
          sub="Không khóa, không hủy từng tác vụ. Một con số tăng lên, mọi thứ của lượt cũ tự rụng.")
    cut = 700

    def bar(x, y, w, h, label, fill, stroke, tc, dash=None, size=14):
        s.rect(x, y, w, h, fill, stroke, 1.8, rx=10, dash=dash)
        s.text(x + w / 2, y + h / 2 + 5, label, size=size, fill=tc, anchor='middle', weight=600)

    bands = [(210, "LƯỢT CŨ", "generation 7"), (340, "KERNEL", "chờ sự kiện"), (470, "LƯỢT MỚI", "generation 8")]
    for (y, a, b) in bands:
        s.rect(56, y, 1168, 100, CARD, LINE, 1.2, rx=12)
        s.text(76, y + 46, a, size=18, weight=800)
        s.text(76, y + 70, b, size=14, fill=DIM)
    s.line(cut, 192, cut, 580, color=ROSE, sw=2.5, dash="8 6", head=False)
    s.text(cut, 184, "NGƯỜI HỌC CHEN LỜI", size=15, fill=ROSE, weight=800, anchor='middle')

    g1 = ('#1a3a45', '#3a5a54', '#b9d3ce')
    bar(270, 236, 160, 48, "Root chờ model", *g1)
    bar(442, 236, 120, 48, "Writer viết", *g1)
    bar(574, 236, 126, 48, "TTS đang đọc…", *g1)
    bar(730, 236, 170, 48, "callback TTS tới trễ", '#2b1a22', ROSE, ROSE, dash="5 4")
    s.line(736, 260, 894, 260, color=ROSE, sw=2, head=False)
    s.text(920, 270, "7 ≠ 8 → bị loại", size=28, fill=ROSE, weight=800)

    s.rect(590, 362, 220, 56, MINTBG, MINT, 3)
    s.text(700, 397, "generation 7 → 8", size=22, weight=800, anchor='middle')
    bar(830, 366, 240, 48, "hủy nói tiếp · bỏ bản phát cũ", CARD, MINT, INK)
    bar(1082, 366, 132, 48, "cấp run_id mới", CARD, MINT, INK)

    bar(730, 496, 120, 48, "Root", MINTBG, MINT, INK)
    bar(862, 496, 120, 48, "Writer", MINTBG, MINT, INK)
    bar(994, 496, 120, 48, "Cửa phát", '#3a2e14', AMB, INK)
    bar(1126, 496, 88, 48, "✓ phát", MINTBG, MINT, MINT)
    s.text(1224, 600, "thời gian →", size=13, fill=DIM, anchor='end')
    s.codebox(56, 608, 1168, 56, ["# Đổi generation TRƯỚC: callback TTS cũ tới đồng thời sẽ bị loại", "generation=prior.generation + 1"], size=13, file="conversation/kernel.py")
    s.save("s06-chen-loi.svg")


# ---------------------------------------------------------------- slide 07
def s07():
    s = S(7, "A · CHỐNG NÓI DỐI",
          [("Định nói ", INK), ("≠", MINT), (" đã nói ", INK), ("≠", MINT), (" đã dạy.", INK)],
          sub="Ba trạng thái khác nhau. Mỗi bước chỉ tiến khi có biên nhận.")
    states = [(56, 190, "preparing", CARD, LINE, INK, ["Root đã chốt ý,", "Writer đang viết"]),
              (290, 230, "queued_for_audio", CARD, LINE, INK, ["đã xếp hàng,", "chưa có tiếng"]),
              (564, 190, "delivering", CARD, LINE, INK, ["đang phát, có thể", "bị người học ngắt"]),
              (798, 190, "delivered ✓", MINTBG, MINT, MINT, ["phát xong,", "có biên nhận ✓"]),
              (1032, 192, "commit_delivery", '#3a2e14', AMB, AMB, ["chỉ chạy khi", "successful = True"])]
    y, h = 300, 64
    for i, (x, w, nm, fill, stroke, tc, cap) in enumerate(states):
        s.rect(x, y, w, h, fill, stroke, 2.5 if stroke != LINE else 1.5)
        s.text(x + w / 2, y + 40, nm, size=17, fill=tc, weight=800, anchor='middle', mono=True)
        s.text(x + w / 2, 394, cap[0], size=15, fill=DIM, anchor='middle')
        s.text(x + w / 2, 414, cap[1], size=15, fill=DIM, anchor='middle')
        if i < 4:
            nx = states[i + 1][0]
            s.line(x + w + 3, y + 32, nx - 5, y + 32, color=MINT, sw=2.5)

    def bracket(x1, x2, label, col):
        s.path(f"M{x1},284 L{x1},272 L{x2},272 L{x2},284", color=col, sw=2.5, head=False)
        s.text((x1 + x2) / 2, 256, label, size=22, fill=col, weight=800, anchor='middle')
    bracket(56, 520, "ĐỊNH NÓI", DIM)
    bracket(798, 988, "ĐÃ NÓI", MINT)
    bracket(1032, 1224, "ĐÃ DẠY", AMB)
    s.text(659, 256, "đang phát: chưa tính", size=14, fill=DIM, anchor='middle')

    s.path("M290,440 L290,454 L754,454 L754,440", color=ROSE, sw=2.2, head=False)
    s.text(522, 446, "bị ngắt (người học chen lời)", size=14, fill=ROSE, anchor='middle', weight=600)
    s.line(522, 454, 522, 484, color=ROSE, sw=2.5)
    s.rect(372, 486, 300, 56, '#2b1a22', ROSE, 2)
    s.text(522, 510, "cancelled", size=18, fill=ROSE, weight=800, anchor='middle', mono=True)
    s.text(522, 531, "không bao giờ tự phát lại", size=14, fill=INK, anchor='middle')
    s.rect(56, 486, 300, 56, '#33290f', AMB, 2, dash="6 4")
    s.text(206, 509, "unconfirmed_after_restart", size=14.5, fill=AMB, weight=800, anchor='middle', mono=True)
    s.text(206, 530, "crash giữa chừng: ghi UNKNOWN", size=13, fill=INK, anchor='middle')
    s.rect(704, 486, 520, 56, '#0f2a33', MINT, 2, dash="6 4")
    s.text(964, 510, "Model tự nhận “em làm tốt rồi” → KHÔNG tính", size=16, fill=ROSE, weight=800, anchor='middle')
    s.text(964, 531, "Chỉ biên nhận phát thành công mới tính là đã dạy", size=14, fill=MINT, anchor='middle')
    s.codebox(56, 580, 1168, 70, ["# Eris *định nói* không đồng nghĩa Eris *đã dạy*.", "if not successful: return"], size=14, file="tutor/executive.py · commit_delivery")
    s.save("s07-bien-nhan.svg")


# ---------------------------------------------------------------- slide 08
def s08():
    s = S(8, "B · HỆ THẦN KINH NHẬN THỨC", [("Nhiều luồng nghĩ. ", INK), ("Một giọng nói.", MINT)],
          sub="Mỗi lời gọi model được xếp làn theo VAI TRÒ, không theo tên model.")
    cards = [("cognitive_lane", "đang làm VAI TRÒ gì", MINT, "xét TRƯỚC", False),
             ("backend", "đi qua cổng nào", LINE, None, False),
             ("resource_class", "có chiếm VRAM máy không", LINE, None, False),
             ("inference_tier", "nhãn cũ, chỉ để tương thích", DIM, "xét SAU", True)]
    for i, (nm, sb, col, tag, dashed) in enumerate(cards):
        y = 186 + i * 86
        s.rect(56, y, 290, 76, CARD, col, 2.2 if col == MINT else 1.5, dash="6 4" if dashed else None)
        s.text(74, y + 32, nm, size=17, weight=800, mono=True, fill=INK if not dashed else DIM)
        s.text(74, y + 56, sb, size=14, fill=DIM)
        if tag:
            s.pill(244, y + 10, 92, 22, tag, MINT if tag == "xét TRƯỚC" else '#183541', None, '#06231f' if tag == "xét TRƯỚC" else DIM, 11)
    for yy in (224, 310, 396):
        s.line(348, yy, 390, 345 + (yy - 310) * 0.25, color=DIM, sw=1.8, head=False)
    s.rect(392, 300, 100, 110, CARD, MINT, 2.5)
    s.text(442, 342, "BROKER", size=18, weight=800, anchor='middle')
    s.text(442, 366, "xếp làn", size=13, fill=DIM, anchor='middle')
    s.text(442, 384, "theo vai trò", size=13, fill=DIM, anchor='middle')
    s.line(494, 330, 538, 270, color=MINT, sw=2.5)
    s.line(494, 380, 538, 466, color=DIM, sw=2.5, dash="6 5")

    s.rect(540, 186, 684, 164, MINTBG, MINT, 2.5)
    s.text(564, 214, [("LÀN BẮT BUỘC", MINT, 800), ("   máy bận vẫn chạy", DIM, 400)], size=18)
    for i, t in enumerate(["Root · root_conversation", "Gia sư · tutor:*", "Writer · public_reply", "Kế hoạch cho lượt người học"]):
        x = 564 + (i % 2) * 330
        y = 232 + (i // 2) * 54
        s.rect(x, y, 316, 44, '#0b2a2c', MINT, 1.4, rx=10)
        s.text(x + 16, y + 28, t, size=16, weight=600)
    s.line(520, 374, 1224, 374, color=ROSE, sw=2.2, dash="8 6", head=False)
    s.text(1224, 368, "máy bận → chỉ cắt phía dưới vạch này", size=14, fill=ROSE, anchor='end', weight=600)
    s.rect(540, 392, 684, 150, '#0e2530', DIM, 1.6, dash="7 5")
    s.text(564, 420, [("LÀN NỀN", DIM, 800), ("   hoãn · gộp · bỏ được", DIM, 400)], size=18)
    nen = ["Observer sau lượt", "Tự khởi (autonomous)", "Seed · planner", "Suy nghĩ nền (neuro)", "Kế hoạch năng lực nền"]
    for i, t in enumerate(nen):
        x = 564 + (i % 3) * 218
        y = 438 + (i // 3) * 50
        s.rect(x, y, 204, 40, '#132f3b', '#2c5160', 1.2, rx=10)
        s.text(x + 14, y + 26, t, size=14.5, fill='#b9d3ce')

    s.rect(56, 562, 560, 88, '#2b1a22', ROSE, 2)
    s.text(76, 586, "TRƯỚC", size=13, fill=ROSE, weight=800, ls=1.5)
    s.text(76, 610, "bước kiểm bắt buộc mang nhãn cũ → rơi xuống làn nền", size=15)
    s.text(76, 632, "→ máy bận thì bị bỏ → Writer nhận UNKNOWN → Eris im lặng", size=15)
    s.line(620, 606, 664, 606, color=MINT, sw=3)
    s.rect(668, 562, 556, 88, MINTBG, MINT, 2.5)
    s.text(688, 586, "SAU", size=13, fill=MINT, weight=800, ls=1.5)
    s.text(688, 610, "Vai trò được xét trước nhãn cũ", size=16, weight=700)
    s.text(688, 634, 'lane = "chat_tool_required"', size=14, fill=MINT, mono=True)
    s.text(1210, 634, "model_router.py", size=11, fill='#4e6d69', anchor='end', mono=True)
    s.save("s08-lane.svg")


# ---------------------------------------------------------------- slide 09
def s09():
    s = S(9, "C · LEARNING KERNEL DETERMINISTIC", [("Model đề xuất. ", INK), ("Kernel có luật mới được chốt.", MINT)],
          sub="Một câu bịa của model không thể ghi vào hồ sơ học.")
    s.rect(56, 180, 320, 150, CARD, DIM, 1.8, dash="7 5")
    s.text(76, 208, "MODEL", size=13, fill=DIM, weight=800, ls=2)
    s.text(76, 236, "RuntimeTutorReasoner", size=15.5, weight=800, mono=True)
    s.text(76, 266, "đề xuất nước dạy", size=15, fill=DIM)
    s.text(76, 288, "chấm câu trả lời tự do", size=15, fill=DIM)
    s.pill(76, 298, 100, 22, "có thể sai", '#2b1a22', ROSE, ROSE, 12)
    s.line(378, 255, 468, 255, color=MINT, sw=2.5)
    s.text(423, 244, "đề xuất", size=13, fill=DIM, anchor='middle')

    s.rect(470, 180, 320, 150, MINTBG, MINT, 2.5)
    s.text(490, 208, "KHUNG ÉP", size=13, fill=MINT, weight=800, ls=2)
    s.text(490, 236, "TutorGuardrailPolicy", size=15.5, weight=800, mono=True)
    s.text(490, 266, "loại câu ngoài khung → ép về khung", size=15, fill='#cfe3df')
    s.text(490, 288, "số câu ≤ giới hạn của pha", size=15, fill='#cfe3df')
    s.line(792, 255, 882, 255, color=MINT, sw=2.5)
    s.text(837, 244, "đã ép", size=13, fill=DIM, anchor='middle')

    s.rect(884, 180, 340, 290, MINTBG, VIO, 2.8)
    s.text(904, 208, "KERNEL", size=13, fill=VIO, weight=800, ls=2)
    s.text(904, 236, "LearningService", size=17, weight=800, mono=True)
    s.text(904, 258, "cửa DUY NHẤT ghi hồ sơ học", size=15, fill='#cfe3df')
    gates = [(274, "① Chấm đủ chắc?", "≥ 0,68 và không “uncertain”"),
             (338, "② Lời dạy đã phát thành công?", "biên nhận delivered")]
    for (gy, a, b) in gates:
        s.rect(904, gy, 300, 52, '#0b2a2c', MINT, 1.6, rx=10)
        s.text(920, gy + 22, a, size=15, weight=700)
        s.text(920, gy + 41, b, size=13, fill=DIM)
    s.line(1054, 328, 1054, 338, color=MINT, sw=2, head=False)
    s.line(1054, 392, 1054, 402, color=MINT, sw=2)
    s.rect(904, 404, 300, 52, '#0f4a47', MINT, 2.2, rx=10)
    s.text(920, 426, "GHI: mastery · bằng chứng", size=15, fill=MINT, weight=800)
    s.text(920, 445, "lịch ôn SM-2 (tính bằng ngày)", size=13, fill='#cfe3df')

    s.text(56, 366, "Mỗi pha dạy chỉ cho phép vài loại câu, có giới hạn số câu", size=15, fill=DIM)
    phases = [("probe", True), ("teach", False), ("practice", True), ("assess", True), ("review", True), ("advance", False)]
    for i, (nm, wait) in enumerate(phases):
        x = 56 + i * 125
        s.rect(x, 384, 108, 40, CARD, MINT if wait else LINE, 1.8)
        s.text(x + 54, 410, nm, size=16, weight=800, anchor='middle', mono=True)
        s.text(x + 54, 444, "chờ trả lời" if wait else "—", size=13, fill=MINT if wait else DIM, anchor='middle', weight=600)
        if i < 5:
            s.text(x + 116, 411, "›", size=20, fill=MINT, anchor='middle', weight=800)

    boxes = [(56, ROSE, "WRITER KHÔNG BAO GIỜ THẤY ĐÁP ÁN", [("to_writer_dict()", True, 16), ("cố ý không có expected_answer", False, 15), ("Đáp án chỉ nằm ở server", False, 15)]),
             (450, MINT, "KHÔNG CÓ MODEL THÌ SAO?", [("ConservativeTutorReasoner", True, 14), ("vẫn đi theo khung,", False, 15), ("chỉ mất phần chấm câu tự do", False, 15)]),
             (844, AMB, "LỊCH ÔN", [("SM-2 · nửa đời quên 14 ngày", False, 16), ("khoảng ôn tối đa 180 ngày", False, 15), ("tính bằng NGÀY, tách khỏi", False, 15), ("continuation lease (30 giây)", False, 15)])]
    for (x, col, tag, lines) in boxes:
        s.rect(x, 500, 378, 146, CARD, col, 2)
        s.text(x + 20, 528, tag, size=13, fill=col, weight=800, ls=1)
        yy = 558
        for (t, mono, sz) in lines:
            s.text(x + 20, yy, t, size=sz, fill=INK if mono or sz == 16 else DIM, mono=mono, weight=700 if mono or sz == 16 else 400)
            yy += 26
    s.save("s09-learning-kernel.svg")


# ---------------------------------------------------------------- slide 10
def s10():
    s = S(10, "TÁC ĐỘNG", [("Người ta trả tiền cho nhân vật. ", INK), ("Người ta bỏ gia sư khô khan.", MINT)], tsize=34)
    s.rect(56, 170, 520, 386, CARD, ROSE, 2.2)
    s.text(80, 206, "NHÂN VẬT GIỮ NGƯỜI", size=16, fill=ROSE, weight=800, ls=2)
    s.text(80, 282, "~162.000", size=58, weight=800)
    s.text(80, 312, "đăng ký trả phí đang hoạt động trên Twitch,", size=15, fill=DIM)
    s.text(80, 334, "hạng 1, gấp hơn 2 lần hạng 2 (Neuro-sama, 01/2026)", size=15, fill=DIM)
    s.rect(80, 362, 472, 1, LINE, None, 0, rx=0)
    s.text(80, 424, "40,5 → 116,7 triệu", size=40, weight=800)
    s.text(80, 456, "người dùng hoạt động hằng tháng của Duolingo,", size=15, fill=DIM)
    s.text(80, 478, "2021 → 2025, đi cùng chiến lược nhân vật cú", size=15, fill=DIM)

    s.rect(704, 170, 520, 386, CARD, MINT, 2.2)
    s.text(728, 206, "GIA SƯ DẠY NHƯNG BỊ BỎ", size=16, fill=MINT, weight=800, ls=2)
    s.text(728, 282, "~1/3", size=58, weight=800)
    s.text(728, 312, "số ngày luyện tập mà học sinh điển hình", size=15, fill=DIM)
    s.text(728, 334, "mới nhắn Khanmigo (trung vị)", size=15, fill=DIM)
    s.rect(728, 362, 472, 1, LINE, None, 0, rx=0)
    s.text(728, 424, "96%", size=58, weight=800)
    s.text(728, 456, "có thử Khanmigo, nhưng lợi ích học tập", size=15, fill=DIM)
    s.text(728, 478, "giống bản không có AI (NBER, 18 trường Tennessee)", size=15, fill=DIM)

    s.circle(640, 360, 74, '#0b1f2a', MINT, 4)
    s.text(640, 360, "ERIS", size=30, fill=MINT, weight=800, anchor='middle')
    s.text(640, 386, "giao điểm", size=13, fill=DIM, anchor='middle')
    s.text(56, 586, "Nguồn: Dexerto 02/01/2026 · Tubefilter 05/01/2026 · Adweek 04/2025 · NBER w35620 (2026)", size=12, fill='#5c7b78')
    s.text(640, 640, [("ERIS", MINT, 800), (" = nhân vật người ta muốn quay lại  ×  bộ não dạy học có luật", INK, 700)], size=24, anchor='middle')
    s.save("s10-tac-dong.svg")


for f in (s04, s05, s06, s07, s08, s09, s10):
    f()
print("done")
