# Clean Dataset Output

Bo nay bat dau tu `scripts/clean_split_jsonl.py`, sau do duoc bo sung va don tay them cho cac nhom desktop, tool, boundary, va supervision rieng cho cortex.

## Output

- `quarantine/desktop_overclaim.jsonl`: mau desktop noi qua capability runtime hien co.
- `quarantine/desktop_safety_manual_review.jsonl`: mau desktop dinh self-harm, illegal, hack de ra tay.
- `quarantine/persona_capability_ambiguous.jsonl`: mau capability nhung tra loi mo ho, chua dang tin de train.
- `quarantine/quarantine_desktop_overinference.jsonl`: mau desktop suy luan qua tay ve cam xuc, sinh ly, hoac hua can thiep ngoai runtime.
- `quarantine/template_artifact.jsonl`: mau lo template hoac bien dang ngon ngu.
- `train/desktop/desktop_grounded_code.jsonl`: desktop grounded code da don bot over-inference.
- `train/desktop/desktop_grounded_general.jsonl`: desktop grounded general da don bot over-inference.
- `train/desktop/desktop_grounded_multiturn.jsonl`: desktop grounded nhieu luot.
- `train/desktop/desktop_no_evidence_refusal.jsonl`: desktop khong du evidence de ket luan manh.
- `train/desktop/desktop_uncertainty_soft_claim.jsonl`: desktop grounded nhung assistant phai suy luan mem va thanh that.
- `train/persona/persona_capability_boundary_strict.jsonl`: mau capability co phu dinh ro gioi han runtime.
- `train/persona/persona_code_help.jsonl`: persona + code/help chat sach.
- `train/persona/persona_emotional_support.jsonl`: persona thien ve nang do cam xuc.
- `train/persona/persona_general_chat.jsonl`: persona chat chung sach.
- `train/persona/persona_safety_refusal.jsonl`: mau safety/refusal de train rieng.
- `train/tools/tool_action_result_grounded.jsonl`: mau action result grounded.
- `train/fe/fe_style_supervision.jsonl`: style supervision ngan cho Fe, duoc sinh tu `persona_general_chat`, `persona_emotional_support`, `persona_code_help`.

## Fe Style Supervision

- File `train/fe/fe_style_supervision.jsonl` duoc tao boi `scripts/build_fe_style_supervision.py`.
- Muc tieu la day model doc nhan ngan nhu `tone=cold_soft`, `warmth=mid`, `stance=grounded`, `attachment=guarded`, thay vi mot khoi policy prose dai.
- Tap nay cung giu cue ngan cho `arc` va `continuity` de renderer co the hoc nhac phong cach ma khong can dump ca bai policy vao prompt runtime.

## Tool Action Summary

Trong `train/tools/tool_action_result_grounded.jsonl`, action duoc luu o truong `action_context.action_name`, khong nam o key top-level `action`.

## Goi Y

- `train/`: dung cho train chinh.
- `SCHEMA.md`: schema mau cho cac file seed them tay va supervision bo sung.
- `quarantine/`: giu rieng de ra tay hoac bo han.
- `scripts/quarantine_desktop_overinference.py`: script don cac mau desktop suy luan qua tay sang quarantine.
- `scripts/build_fe_style_supervision.py`: script tao tap supervision ngan cho Fe tu cac file persona da co.
