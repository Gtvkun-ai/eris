# -*- coding: utf-8 -*-
"""Tao file Word thuyet trinh ERIS de nop vong so khao."""
from docx import Document
from docx.shared import Pt, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

ACCENT = RGBColor(0x1F, 0x4E, 0x79)       # xanh dam
ACCENT2 = RGBColor(0x2E, 0x75, 0xB6)      # xanh
GREY = RGBColor(0x59, 0x59, 0x59)

doc = Document()

# ---- Base style ----
normal = doc.styles["Normal"]
normal.font.name = "Times New Roman"
normal.font.size = Pt(12)
rpr = normal.element.get_or_add_rPr()
rfonts = rpr.get_or_add_rFonts()
rfonts.set(qn("w:eastAsia"), "Times New Roman")

for i in range(1, 4):
    h = doc.styles[f"Heading {i}"]
    h.font.name = "Times New Roman"
    h.font.color.rgb = ACCENT
    h.font.size = Pt({1: 15, 2: 13, 3: 12}[i])


def set_spacing(p, before=0, after=6, line=1.3):
    pf = p.paragraph_format
    pf.space_before = Pt(before)
    pf.space_after = Pt(after)
    pf.line_spacing = line


def para(text="", bold=False, italic=False, size=12, color=None,
         align=None, before=0, after=6, line=1.3):
    p = doc.add_paragraph()
    if align:
        p.alignment = align
    r = p.add_run(text)
    r.bold = bold
    r.italic = italic
    r.font.size = Pt(size)
    if color:
        r.font.color.rgb = color
    set_spacing(p, before, after, line)
    return p


def justify(p):
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    return p


# ======================= TRANG BIA / TIEU DE =======================
t = para("ĐỀ XUẤT DỰ ÁN", bold=True, size=13, color=GREY,
         align=WD_ALIGN_PARAGRAPH.CENTER, after=2)
title = doc.add_paragraph()
title.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = title.add_run("ERIS — GIA SƯ AI ĐỒNG HÀNH")
r.bold = True
r.font.size = Pt(22)
r.font.color.rgb = ACCENT
set_spacing(title, 0, 2)

sub = doc.add_paragraph()
sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = sub.add_run("Evolving Runtime for Intelligent Study")
r.italic = True
r.font.size = Pt(13)
r.font.color.rgb = ACCENT2
set_spacing(sub, 0, 10)

slogan = doc.add_paragraph()
slogan.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = slogan.add_run("“Mọi AI đều trả lời bạn. Eris là cái duy nhất khiến bạn muốn học.”")
r.italic = True
r.font.size = Pt(12.5)
r.font.color.rgb = GREY
set_spacing(slogan, 0, 10)

team = para("Nhóm thực hiện: Children of the Holy Leader Ho Chi Minh",
            bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, after=14)

# duong ke
hr = doc.add_paragraph()
pPr = hr._p.get_or_add_pPr()
pBdr = OxmlElement("w:pBdr")
bottom = OxmlElement("w:bottom")
bottom.set(qn("w:val"), "single")
bottom.set(qn("w:sz"), "6")
bottom.set(qn("w:space"), "1")
bottom.set(qn("w:color"), "1F4E79")
pBdr.append(bottom)
pPr.append(pBdr)
set_spacing(hr, 0, 10)


# ======================= 1. BOI CANH =======================
doc.add_heading("1. Bối cảnh", level=1)
justify(para(
    "Thời đại công nghệ 4.0 phát triển mạnh mẽ song hành với sự bùng nổ của trí tuệ nhân tạo. "
    "Chỉ với một câu lệnh, chúng ta có ngay đáp án bài toán, công thức nấu ăn hay dữ kiện lịch sử "
    "thông qua các AI agent như Gemini, Copilot. Mọi thứ đều có sẵn, không cần tốn công tìm hiểu."))
justify(para(
    "Nhưng chính sự tiện lợi đó đang tạo ra một thế hệ chỉ nhớ kết quả mà bỏ quên quá trình — và "
    "cùng với nó là công sức của những người đi trước."))

p = doc.add_paragraph()
r = p.add_run("Ví dụ lịch sử. ")
r.bold = True
r.add_text = None
p.add_run(
    "Nhiều người nhớ Đảng Cộng sản Việt Nam thành lập năm 1930, nhưng không biết trước đó nước ta "
    "từng có ba tổ chức cộng sản riêng biệt — Đông Dương Cộng sản Đảng, An Nam Cộng sản Đảng và "
    "Đông Dương Cộng sản Liên đoàn — rồi mới hợp nhất. Ta quen với quốc hiệu “Việt Nam”, nhưng không "
    "phải ai cũng tường tận những tên gọi hào hùng trước đó: Văn Lang, Âu Lạc, Đại Cồ Việt, Đại Việt.")
justify(p); set_spacing(p, 0, 6)

p = doc.add_paragraph()
r = p.add_run("Ví dụ lập trình. ")
r.bold = True
p.add_run(
    "Ta tìm được một đoạn code ngắn gọn và tưởng đó là thành quả dễ dàng, mà không biết người viết đã "
    "trầy trật qua vô số cách giải. Hơn nữa, code ngắn chưa chắc chạy nhanh nhất — đôi khi một thuật "
    "toán dài hơn lại cho hiệu suất vượt trội. Chính tư duy ấy mới là nền tảng xây nên những mô hình AI "
    "xử lý dữ liệu trong chớp mắt mà ta đang dùng hôm nay.")
justify(p); set_spacing(p, 0, 6)

justify(para(
    "Hệ quả: người học bị mắc kẹt trong vòng lặp của người đi trước — tiêu thụ kết quả mà không hiểu, "
    "không có lối thoát để phát triển cái mới."))


# ======================= 2. VAN DE COT LOI =======================
doc.add_heading("2. Vấn đề cốt lõi", level=1)
justify(para(
    "Ngoài kia có hàng trăm AI dạy giỏi. Về mặt giải bài, chúng ngang nhau — thậm chí hơn. Nhưng người "
    "học vẫn bỏ cuộc. Vì sao?"))
q = para("Người ta bỏ học không phải vì thiếu người dạy. Mà vì học một mình thì cô đơn, và chẳng ai giữ mình lại.",
         bold=True, italic=True, color=ACCENT, after=8)
q.alignment = WD_ALIGN_PARAGRAPH.CENTER

for b in [
    "Người học dễ mất tập trung khi gặp tài liệu dài, khó hoặc thiếu phản hồi tức thời.",
    "Chatbot hỏi–đáp thông thường thiếu tính liên tục, khó theo sát tiến độ và mục tiêu học tập.",
    "Người học cần một trải nghiệm hợp nhất: giải thích bài, luyện tập, nhắc lịch và giao tiếp tự nhiên — chứ không phải mỗi thứ một nơi.",
]:
    bp = doc.add_paragraph(style="List Bullet")
    bp.add_run(b)
    set_spacing(bp, 0, 4)

mandela = para("“Sự sụp đổ của giáo dục chính là sự sụp đổ của một quốc gia.” — Nelson Mandela",
               italic=True, color=GREY, after=6)
mandela.alignment = WD_ALIGN_PARAGRAPH.CENTER


# ======================= 3. GIAI PHAP =======================
doc.add_heading("3. Giải pháp: biến AI thành gia sư, không phải máy trả lời", level=1)
justify(para(
    "Thay vì một cuộc vấn đáp cứng nhắc “một câu hỏi — một đáp án”, nhóm đề xuất biến chính AI thành một "
    "người gia sư tại nhà. ERIS ra đời để mang đến cho học sinh, sinh viên:"))
for b in [
    "Một gia sư lạ mà thân thuộc — luôn ở bên.",
    "Một người bạn đồng hành, dõi theo và tiếp động lực.",
    "Sự hứng thú trong lúc học, để việc tìm hiểu không còn buồn chán.",
    "Khả năng lên lịch học thông minh, nắm chắc kiến thức.",
    "Một làn gió mới cho chatbot.",
]:
    bp = doc.add_paragraph(style="List Bullet")
    bp.add_run(b)
    set_spacing(bp, 0, 4)

doc.add_heading("Điểm khác biệt mà ChatGPT về bản chất không thể có", level=2)
justify(para(
    "Eris không phải chatbot stateless. Nó là một cognitive runtime — có trí nhớ sống, ngữ cảnh liên tục và "
    "khả năng chủ động. Nhờ đó Eris làm được ba điều mà AI thường bỏ trống:"))
diffs = [
    ("Nhớ bạn như một con người, không phải như lịch sử chat.",
     "Eris nhớ hôm qua bạn vật lộn với bài gì, nhớ bạn hay nản lúc nào, nhớ bạn tiến bộ tới đâu."),
    ("Có mặt cả khi bạn chưa mở app.",
     "Eris chủ động nhắc, giữ nhịp học như một người bạn thật — thay vì ngồi im chờ bạn hỏi."),
    ("Quan tâm trạng thái, không chỉ câu trả lời.",
     "Khi bạn nản, Eris không giảng tiếp — nó dừng lại, động viên, rồi mới học tiếp."),
]
for i, (h, d) in enumerate(diffs, 1):
    p = doc.add_paragraph(style="List Number")
    r = p.add_run(h + " ")
    r.bold = True
    p.add_run(d)
    set_spacing(p, 0, 4)

p = para("", after=6)
r = p.add_run("Chúng tôi không làm một AI dạy tốt hơn. Chúng tôi làm một AI khiến bạn muốn học.")
r.bold = True
r.font.color.rgb = ACCENT


# ======================= 4. PHAN BIEN =======================
doc.add_heading("4. Dùng AI để học có khiến ta mắc kẹt trong vòng lặp người đi trước?", level=1)
justify(para("Không — nếu AI khơi được hứng thú và sự chú tâm.", bold=True))
justify(para(
    "Khi người học thực sự hứng thú và tập trung tìm lời giải, họ có khả năng tạo ra cái mới cao hơn nhiều "
    "so với việc chép lại đáp án."))
for b in [
    "Archimedes chú tâm tìm lời giải mới reo lên “Eureka!” — tri thức mới sinh ra từ sự tập trung, không phải từ việc tra cứu.",
    "Vắc-xin COVID-19 là thành quả của những nhà khoa học miệt mài nghiên cứu, không phải của người đi tìm đáp án có sẵn.",
]:
    bp = doc.add_paragraph(style="List Bullet")
    bp.add_run(b)
    set_spacing(bp, 0, 4)
justify(para(
    "Eris được thiết kế để nuôi chính sự chú tâm đó — dẫn người học hiểu “vì sao”, chứ không dừng ở “đáp án là gì”."))


# ======================= 5. ERIS LA GI =======================
doc.add_heading("5. ERIS là gì (về mặt kỹ thuật)", level=1)
justify(para(
    "Eris là một AI Agent đóng vai bạn đồng hành học tập, thể hiện qua nhân vật Live2D có biểu cảm, chuyển động "
    "và giọng nói. Thay vì chỉ trả lời, Eris duy trì mạch hội thoại, nhận biết ngữ cảnh học tập (khi được người "
    "dùng cho phép), giải thích theo năng lực và chủ động hỗ trợ xây thói quen học."))
justify(para(
    "Điểm khác biệt nằm ở sự kết hợp ba lớp: gia sư AI biết dùng công cụ + nhân vật Live2D tạo cảm giác hiện diện "
    "+ hệ thống theo dõi mục tiêu học có kiểm soát. Sự thú vị không chỉ đến từ hoạt ảnh, mà từ cách đặt câu hỏi, "
    "gợi ý đúng lúc và phản hồi cá nhân hóa."))

doc.add_heading("Các nhóm chức năng dự kiến", level=2)
rows = [
    ("Đọc & giải thích", "Tiếp nhận văn bản/PDF được cho phép; tóm tắt, giải thích từng bước, dẫn lại phần tài liệu liên quan."),
    ("Đối thoại theo ngữ cảnh", "Ghi nhớ mục tiêu, chủ đề đang học, câu hỏi dang dở và mức độ hiểu; đổi cách giải thích khi cần."),
    ("Gia sư chủ động", "Đặt câu hỏi kiểm tra, gợi ý bài tập, nhận xét câu trả lời, đề xuất ôn tập ngắt quãng."),
    ("Lập kế hoạch", "Nhận lịch rảnh, hạn nộp bài, mức ưu tiên; đề xuất thời khóa biểu, nhắc lịch, cho phép chỉnh sửa."),
    ("Nhân vật Live2D", "Đồng bộ trạng thái hội thoại với biểu cảm, hoạt ảnh, giọng nói; có phụ đề, tùy chọn tắt tiếng."),
    ("An toàn & kiểm soát", "Xin phép trước khi đọc dữ liệu cá nhân; cho xóa lịch sử/ngữ cảnh; xác nhận trước khi đổi lịch."),
]
table = doc.add_table(rows=1, cols=2)
table.style = "Light Grid Accent 1"
table.alignment = WD_TABLE_ALIGNMENT.CENTER
hdr = table.rows[0].cells
for c, txt in zip(hdr, ["Nhóm chức năng", "Mô tả"]):
    c.paragraphs[0].add_run(txt).bold = True
for name, desc in rows:
    cells = table.add_row().cells
    cells[0].paragraphs[0].add_run(name).bold = True
    cells[1].paragraphs[0].add_run(desc)
table.columns[0].width = Inches(1.9)
table.columns[1].width = Inches(4.3)

doc.add_heading("Luồng hoạt động điển hình", level=2)
flow = [
    "Người dùng hỏi / cung cấp tài liệu",
    "Xác định ý định & quyền truy cập",
    "Truy xuất nội dung phù hợp",
    "Xây lời giải thích hoặc gọi công cụ",
    "Kiểm tra tính phù hợp, ghi nguồn khi có",
    "Hiển thị lời thoại + giọng nói + biểu cảm Live2D",
    "Cập nhật tiến độ học (nếu người dùng đồng ý)",
]
for i, step in enumerate(flow):
    p = doc.add_paragraph()
    r = p.add_run(f"{i+1}. {step}")
    set_spacing(p, 0, 2)
    if i < len(flow) - 1:
        a = doc.add_paragraph()
        a.add_run("↓").font.color.rgb = ACCENT2
        set_spacing(a, 0, 2)

doc.add_heading("Tóm tắt kiến trúc", level=2)
justify(para(
    "Kho mã là một hệ thống trợ lý đa thành phần: Python làm lõi, Godot/C# làm phần hiển thị, VS Code extension "
    "làm công cụ tích hợp. Có các lớp riêng cho điều phối hội thoại, trí nhớ, nhận thức, nhà cung cấp LLM, hành "
    "động và telemetry."))
justify(para(
    "(Nhận định dựa trên cấu trúc mã, chưa xác nhận toàn bộ luồng thực tế. Rủi ro: diện tích hệ thống lớn, nhiều "
    "module runtime; cần kiểm thử tích hợp để xác minh ranh giới trách nhiệm.)",
    italic=True, color=GREY))


# ======================= 6. LO TRINH =======================
doc.add_heading("6. Lộ trình triển khai", level=1)
phases = [
    ("Giai đoạn 1 — MVP kiểm chứng giá trị.",
     "Một trải nghiệm học thực sự dùng được: chat theo tài liệu, giải thích có dẫn nguồn, nhớ ngữ cảnh trong phiên, "
     "Live2D với vài trạng thái cơ bản, lịch học có xác nhận. Chưa triển khai nhiều worker hay cơ chế tự chủ phức tạp."),
    ("Giai đoạn 2 — Gia sư thích nghi.",
     "Thêm kiểm tra mức độ hiểu, bộ câu hỏi luyện tập, hồ sơ năng lực theo chủ đề, đề xuất lịch ôn tập. Đánh giá bằng "
     "việc người dùng trả lời đúng sau khi được hướng dẫn — không chỉ bằng độ tự nhiên của lời thoại."),
    ("Giai đoạn 3 — Agent chủ động có giới hạn.",
     "Eris tự đề xuất bước tiếp theo dựa trên mục tiêu và lịch đã cho phép, nhưng phân biệt rõ “đề xuất” với “thực thi”. "
     "Hành động tác động tới lịch/tệp/thông báo đều phải có quyền và cơ chế xác nhận."),
    ("Giai đoạn 4 — Trải nghiệm hội thoại nâng cao.",
     "Hội thoại nhiều lượt mượt hơn, phản ứng Live2D theo ngữ cảnh, âm thanh streaming, xử lý ngắt lời và độ trễ, "
     "chuyển mượt từ trò chuyện sang giảng bài. Không dùng biểu cảm hay suy đoán tâm trạng như kết luận chắc chắn về người dùng."),
]
for h, d in phases:
    p = doc.add_paragraph()
    r = p.add_run(h + " ")
    r.bold = True
    r.font.color.rgb = ACCENT2
    p.add_run(d)
    justify(p)
    set_spacing(p, 0, 6)


# ======================= 7. TIEU CHI NGHIEM THU =======================
doc.add_heading("7. Tiêu chí nghiệm thu", level=1)
for b in [
    "Người dùng tải tài liệu và nhận giải thích tham chiếu đúng đoạn nguồn.",
    "Mỗi buổi học có ít nhất một vòng hỏi–đáp, kiểm tra hiểu bài và phản hồi điều chỉnh.",
    "Lịch học được đề xuất theo thời gian rảnh và chỉ lưu sau khi xác nhận.",
    "Lời thoại, phụ đề, TTS và biểu cảm không làm mất khả năng theo dõi nội dung.",
    "Dữ liệu riêng tư có quyền truy cập rõ ràng; người dùng xem, sửa, xóa được.",
    "Có bộ test và demo end-to-end tái lập được trên môi trường mới.",
]:
    bp = doc.add_paragraph(style="List Bullet")
    bp.add_run(b)
    set_spacing(bp, 0, 4)


# ======================= 8. RUI RO =======================
doc.add_heading("8. Rủi ro cần kiểm soát", level=1)
justify(para(
    "Các rủi ro chính: AI giải thích sai nhưng tự tin; trích dẫn sai tài liệu; chi phí gọi mô hình tăng; trễ âm thanh; "
    "quá tải ngữ cảnh; cá nhân hóa gây cảm giác xâm phạm riêng tư."))
p = doc.add_paragraph()
r = p.add_run("Đối sách ngay từ MVP: ")
r.bold = True
p.add_run("cơ chế dẫn nguồn, biểu thị mức độ không chắc chắn, giới hạn công cụ và đo lường thực nghiệm.")
justify(p); set_spacing(p, 0, 6)


# ======================= 9. KET LUAN =======================
doc.add_heading("9. Kết luận", level=1)
justify(para(
    "Eris hoàn toàn khả thi để trở thành một nền tảng gia sư AI tương tác cao — kết hợp học cá nhân hóa, giao tiếp tự "
    "nhiên và quản lý kế hoạch học. Hướng đi đúng là bắt đầu từ một phiên bản nhỏ nhưng hoàn chỉnh về nghiệp vụ, "
    "chứng minh hiệu quả giải thích và hỗ trợ học, rồi mới mở rộng khả năng chủ động và biểu đạt cảm xúc."))

box = doc.add_paragraph()
box.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = box.add_run("Tham vọng của chúng tôi:")
r.bold = True
r.font.color.rgb = ACCENT
set_spacing(box, 6, 2)
box2 = doc.add_paragraph()
box2.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = box2.add_run("Eris không chỉ trả lời “đáp án là gì”, mà giúp người học hiểu “vì sao”, "
                 "nhận ra “mình chưa hiểu ở đâu”, và biết “nên học gì tiếp theo”.")
r.italic = True
set_spacing(box2, 0, 8)

doc.save("ERIS_De_xuat_du_an.docx")
print("DONE")
