# Báo cáo: summary Gemini chạy nền + tắt OCR

Mức bằng chứng: đọc source, `verify_async_summary_no_ocr.py` với adapter Gemini giả (ngủ 6 s) và pytest với fake. Không có quan sát live, không chạy bản portable, không gọi Gemini thật. Không commit, không push, không đụng `C:\Users\Gtvkun\Documents\eris` hay `.env`.

## Đã đổi (file)
- `src/memory/living_user/service.py`: worker `ERIS-LivingUserEpisode`; snapshot dưới lock, gọi Gemini ngoài lock, lưu episode rồi trim đúng dòng của snapshot; single-flight, timeout, backoff, hoãn khi user đang chat; `request_consolidation`, `consolidation_status`, `stop_consolidation`; trace `episode_consolidation`.
- `src/memory/living_user/episode_builder.py`: `EpisodeModelError`, `build(..., allow_fallback, timeout)`.
- `src/memory/living_user/gemini_adapter.py`: `_LANE_LOCK` có giới hạn chờ, `timeout` truyền xuống HTTP.
- `src/memory/living_user/episode_rollup.py`: kết quả failed có `detail`, log warning.
- `src/screen/ocr_config.py` (mới), `src/screen/ocr_worker.py`, `src/runtime/chat_perception.py`, `src/screen/screen_relevance_router.py`, `src/actions/capability_runtime.py`: công tắc `ERIS_SCREEN_OCR_ENABLED` (mặc định tắt).
- `.env.example`: các biến `ERIS_LIVING_USER_EPISODE_*` và `ERIS_SCREEN_OCR_ENABLED`.
- Test mới: `test_living_user_async_consolidation.py` (12), `test_screen_ocr_switch.py` (11). Ba test cũ bật `ERIS_SCREEN_OCR_ENABLED=1`, giữ nguyên assertion.
- Docs: mục mới cuối `docs/knowledge/2026-10-14-eris-runtime-lessons.md`.

## Trước / sau (script, sleep 6 s)
| Lời gọi trong lúc Gemini đang tóm tắt | Trước | Sau |
|---|---|---|
| capture_interpretation_context | 5,661 s | 0,001 s |
| TurnMemoryPipeline._enqueue_curator | 6,012 s | 0,005 s |
| record_conversation_turn | 6,003 s | 0,016 s |
| ingest hot path | 6,017 s | 0,019 s |

`results_after.json`: check 1, 2, 3, 4, 5, 7 PASS; check 6 là REPORT (không có pass/fail). Gemini lỗi: trước đó ghi episode heuristic và xóa buffer; nay giữ buffer, không ghi episode, lên lịch retry. OCR tắt: không import RapidOCR/pytesseract, không pip, không `force_ocr`; "nhìn màn hình đi" chụp và gọi vision ngay trong lượt.

Pytest (12 file): 240 passed, 5 failed. Đúng 5 lỗi có sẵn trong baseline (2 trong `test_living_user_memory_v39.py`, 2 trong `test_architecture_c_runtime_regressions.py`, 1 trong `test_deep_environment_native_v2.py`). Output: `_final_tests.txt`.

## Chat dùng gì khi summary mới chưa xong
Chat không chờ worker. Nó đọc: (1) các episode đã lưu trước đó (`episode_store`), (2) recap rollup nếu hash coverage còn khớp, (3) tối đa 12 turn thô gần nhất trong buffer. Nếu chưa có episode nào thì không có episode và không có summary thay thế. Khi Gemini xong, episode mới được lưu (gộp vào episode cùng session) rồi các turn đã tóm tắt mới bị trim khỏi buffer. Nếu Gemini lỗi hoặc quá 60 s, các turn ở lại buffer và retry sau 60 s, tăng dần tới 600 s. Ngoại lệ: không có adapter, hoặc buffer ≥ 40 dòng (giới hạn cứng 48) thì ghi episode heuristic để khỏi mất turn.

## Kết luận về ValueError
Chưa xác định được nguyên nhân gốc, vì không có quan sát live. Từ source và script (check 7): anchor không nằm trong `allowed_anchors`, hơn 8 segment và anchor trùng đều cho `status=failed error=ValueError`. File rollup JSON hỏng cho `JSONDecodeError` (lớp con của ValueError nhưng tên in ra khác), nên `ValueError` trơn không đến từ JSON hỏng. Thay đổi đã làm: result có `detail` (ví dụ `invalid_rollup_segment`) và log warning, nên lần live tới sẽ biết nhánh nào.

## False positive (chưa sửa, cần quyết định)
Bằng chứng (check 6, qua `prepare_turn` với router thật): ba câu 03/11 "vụ đó lâu rồi á", "nó ko hiểu ý tôi. làm ko hợp ý", "cái này ko hay. tôi tâm sự …, fe tệ quá nha" đều ra `references_screen=1, inherited=1, mode=vision, needs_visual=0`, không chụp ngay, `pending_vision` được xếp hàng. Nguyên nhân: `screen_anaphora_rescue.py` so khớp chuỗi đã bỏ dấu, anchor `anh`/`code` từ lượt Eris trước và deictic `no`/`do`/`day`. Hậu quả: lượt sau tốn một lần chụp và gọi vision. Có OCR hay không đều như nhau. Gợi ý một dòng: so khớp bản có dấu (`ảnh`, `nó`, `đó`) hoặc yêu cầu thêm động từ xem/nhìn/đọc. Không sửa vì đổi routing của câu nối tiếp thật. `intention_authority.py` cũng khớp `mo` (mở) sau khi bỏ dấu.

## Rủi ro còn lại
- Worker digest vẫn bị chiếm trong lúc `rollup_episodes()` và lời gọi profile-ops của dream (không giữ lock của chat).
- Bản portable chưa sync; chưa chạy live; latency và lỗi Gemini thật chưa đo.
- Chi phí vision thay OCR chưa đo; UIA text vẫn dùng khi đủ tin cậy.
- Retry và backoff nằm trong bộ nhớ; sau restart, buffer còn lại được xử lý ở lần đổi session hoặc `dream()` kế tiếp.
- `src/tests/test_run_20260811_repairs.py::test_forced_ocr_refresh_does_not_wait_forever_on_busy_capture_lock` treo sẵn (không có code đọc `ERIS_SCREEN_CHAT_REFRESH_LOCK_TIMEOUT_SEC`); không đưa vào sweep, không sửa.
- `test_companion_memory_authority_consolidation.py::test_living_user_competence_claim_is_context_only_not_teaching_authority` fail khi FEAT-002 chạy; cùng triệu chứng với 2 lỗi v39 có sẵn, chưa xác nhận baseline HEAD. Nằm ngoài sweep của FEAT-004.
- Không có gì được commit; các thay đổi còn là file chưa commit trong working tree.
