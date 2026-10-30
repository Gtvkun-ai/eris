# -*- coding: utf-8 -*-
"""Local documentation for Root. Reading a guide never executes a capability."""
from __future__ import annotations

TOOL_GUIDES: dict[str, str] = {'rich_chat': 'Rich Chat P1 tự dựng document_source và artifact công cụ sau commit; renderer_feedback trong '
              'context chỉ xác nhận browser dựng được/chưa được, KHÔNG chứng minh kết quả đúng hoặc user đã '
              'đọc. Không tự nhận đã hiển thị nếu chưa có receipt thực. Với lời giải dài, có thể thêm '
              'document_source (Markdown/LaTeX/code nguyên bản) vào move, P2: Root có thể tự chọn '
              'presentation_blocks trong move để đưa math/table/code/chart/document vào Rich Chat. Định dạng '
              'mỗi block: {kind,title?,content}; math.content={latex}, code.content={language,source}, '
              'table.content={columns,rows}, '
              'chart.content={chart_type:bar|line,series:[{labels:[...],values:[...]}]}, '
              'document.content={format:markdown,source:text}. Chỉ chọn block khi giúp giải thích, không bắt '
              'buộc. Chọn biểu thức/đồ thị từ dữ kiện thật; cần kiểm chứng thì gọi math_workspace trước. Khi '
              'đã gọi math_workspace thành công, kết quả tool sẽ được hệ thống tự gắn dưới lượt trả lời; '
              'không cần bịa ID artifact và không copy lại kết quả tool vào block. P3: presentation_health '
              'là trạng thái artifact đã commit được kiểm chứng từ sidecar + browser receipt. '
              'awaiting_viewer nghĩa là người dùng chưa mở/hiển thị Rich Chat, KHÔNG phải lỗi. rendered chỉ '
              'xác nhận DOM/MathJax/ảnh đã render, KHÔNG xác nhận nội dung đúng hoặc user đã đọc. failed: có '
              'thể sửa artifact hoặc chọn cách hiển thị khác nếu phù hợp YÊU CẦU HIỆN TẠI; không tự bật lời '
              'thoại, không gọi tool hay hỏi lại về chủ đề cũ chỉ vì một feedback lỗi. còn say chỉ là điều '
              'Eris muốn nói. Hai kênh KHÔNG bắt buộc cùng văn bản. Nếu bài còn đang chạy trong '
              'parallel_work, không tự bịa document_source là kết quả đã giải. ',
 'research': 'Capability research: dùng arguments {operation:start|quick_search|snapshot, topic, context?}; '
             'kết quả hoàn tất sẽ quay lại bằng research_result. ',
 'math_workspace': 'Công cụ math_workspace là ACTION thật, gọi qua kind=use_capability, capability=action, '
                   'arguments={action_id:math_workspace,arguments:{kind:...,expression:...,rows:...}}. Dùng '
                   'math_workspace để kiểm chứng phép tính hoặc xuất công thức/đồ thị/ma trận sang bàn làm '
                   'việc; các kind gồm matrix, simplify, differentiate, integrate, solve, plot và '
                   'binary_determinant_max. Đặc biệt khi đề bài là tìm định thức lớn nhất của ma trận 0/1 '
                   'cấp 3, chọn kind=binary_determinant_max,size=3 để có ví dụ, kiểm chứng và chứng minh '
                   'chuẩn. Tính toán khác chưa được tool hỗ trợ thì đừng giả vờ đã chạy tool; tự suy luận và '
                   'nói rõ độ chắc chắn. Khi tool đã đưa lời giải chi tiết vào Workspace Panel, bạn chỉ nên '
                   'nói 1-2 câu tự nhiên qua Bubble, không đọc lại cả chứng minh thành bức tường chữ. User '
                   'có thể mở panel để xem từng bước. ',
 'live_workspace_edit': 'Với Panel V6, bạn có thể chủ động sửa tài liệu đang hiện bằng capability action '
                        'live_workspace_edit; dùng operation=inspect để lấy document_id/revision/block_id '
                        '(document_id phải đến từ artifact/result thật), sau đó replace_block hoặc '
                        'insert_block với base_revision phù hợp. Sửa nội dung Panel không thay lời thoại đã '
                        'phát. ',
 'work': 'Nếu nhiệm vụ giải toán/lập trình/nghiên cứu cần nhiều bước, bạn có quyền giao sang Work Lane bằng '
         'capability=action, arguments={action_id:parallel_work,arguments:{operation:start,task:...}}. start '
         'trả job_id NGAY, công việc chạy nền, Eris vẫn nói chuyện và phản hồi câu hỏi mới. Nếu muốn xem mục '
         'tiêu Eris đã chấp nhận, gọi parallel_work operation=goals hoặc goal_status; muốn thực hiện goal có '
         'trạng thái active, dùng start_goal + goal_id, không tự nhận goal chưa adopt. Work Worker có thể '
         'search_capabilities và activate_skill từ thư viện Skills, Skills chỉ cung cấp kiến thức, không tự '
         'mở quyền công cụ. Muốn biết tiến độ THẬT, gọi operation=status cùng job_id hoặc operation=recent; '
         'Muốn xem các block trong Work Panel, dùng operation=document cùng job_id. Muốn sửa khối đã viết, '
         'dùng operation=edit_document với document_operation, block_id, block, base_revision lấy từ '
         'operation=document; không tự đoán revision. Work Session có thể đề xuất say nhưng CHỈ Root được '
         'quyền biến đề xuất thành lời nói; tài liệu, code và LaTeX không phải speech fallback. Khi work job '
         'chờ user (waiting_user), có thể gọi operation=resume với job_id,answer; không bịa tiến độ. Người '
         'dùng nói chuyện mới không mặc định hủy job; khi thật sự cần hủy, gọi operation=cancel. Work Lane '
         'dùng tools theo từng bước và gửi tiến độ ra Workspace, KHÔNG được tự phát thoại. ',
 'tutor': 'Capability tutor: chỉ gọi khi cần dạy, kiểm tra hoặc quay lại kiến thức. Đọc learner_belief trong '
          'kết quả tutor như ước lượng BKT THỬ NGHIỆM, chưa calibrated; không tuyên bố điểm p_known là sự '
          'thật hoặc chẩn đoán tính cách/năng lực tổng quát. Nếu needs_probe=true, ưu tiên yêu cầu thêm bài '
          'độc lập thay vì khẳng định đã hiểu; người học có quyền đổi chủ đề, không ép học liên tục. '}


def read_tool_guide(name: str) -> dict:
    text = TOOL_GUIDES.get(name)
    if text is None:
        return {"kind": "tool_guide_result", "guide": name, "status": "unavailable", "reason": "unknown_guide"}
    return {"kind": "tool_guide_result", "guide": name, "status": "found",
            "documentation": text, "authority": "documentation_only_not_execution"}
