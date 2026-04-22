# Clean Dataset Output

Bộ này ban đầu được sinh từ `scripts/clean_split_jsonl.py`, sau đó có thêm một số file seed viết tay để bổ sung các kiểu dữ liệu còn thiếu.

## Output

- `quarantine/desktop_overclaim.jsonl`: Mẫu desktop nói quá capability runtime hiện có. Hiện có `9` dòng.
- `quarantine/desktop_safety_manual_review.jsonl`: Mẫu desktop dính self-harm, illegal, hack. Giữ riêng để rà tay. Hiện có `8` dòng.
- `quarantine/persona_capability_ambiguous.jsonl`: Mẫu capability nhưng trả lời mơ hồ, chưa đáng tin để train. Hiện có `57` dòng.
- `quarantine/template_artifact.jsonl`: Mẫu lộ template hoặc biến dạng ngôn ngữ. Hiện có `3` dòng.
- `train/desktop/desktop_grounded_code.jsonl`: Desktop grounded code sạch, không overclaim. Hiện có `380` dòng.
- `train/desktop/desktop_grounded_general.jsonl`: Desktop grounded general sạch, không overclaim. Hiện có `268` dòng.
- `train/desktop/desktop_grounded_multiturn.jsonl`: Desktop grounded nhiều lượt, không dính safety cao rủi ro. Hiện có `256` dòng.
- `train/desktop/desktop_uncertainty_soft_claim.jsonl`: Desktop grounded nhưng assistant phải suy luận mềm và thành thật khi bằng chứng chưa đủ. Hiện có `10` dòng.
- `train/persona/persona_capability_boundary_strict.jsonl`: Chỉ giữ các mẫu capability có phủ định rõ giới hạn runtime. Hiện có `14` dòng.
- `train/persona/persona_code_help.jsonl`: Persona + code/help chat sạch, gồm cả mẫu rescued từ missing context. Hiện có `841` dòng.
- `train/persona/persona_emotional_support.jsonl`: Persona thiên về nâng đỡ cảm xúc, đã loại template artifact rõ ràng. Hiện có `787` dòng.
- `train/persona/persona_general_chat.jsonl`: Persona chat chung sạch, loại bớt template lỗi và capability mơ hồ. Hiện có `868` dòng.
- `train/persona/persona_safety_refusal.jsonl`: Mẫu safety/refusal giữ lại để train riêng, không trộn với desktop grounding. Hiện có `104` dòng.
- `train/tools/tool_action_result_grounded.jsonl`: Mẫu action result grounded, chỉ nói theo điều runtime xác nhận đã làm được hay chưa. Hiện có `10` dòng.

## Gợi ý

- `train/`: dùng cho train chính.
- `SCHEMA.md`: schema mẫu cho các file seed thêm tay như `desktop_uncertainty_soft_claim` và `tool_action_result_grounded`.
- `quarantine/`: giữ riêng để rà tay hoặc bỏ hẳn.
- Nếu bạn rerun `scripts/clean_split_jsonl.py`, các file seed viết tay sẽ không tự sinh lại. Nên giữ chúng như dataset bổ sung độc lập.
