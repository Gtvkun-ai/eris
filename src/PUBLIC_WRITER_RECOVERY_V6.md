# Public Writer Recovery V6

## Mục tiêu

V6 sửa lỗi direct-user chat có model/reasoning nhưng câu public bị mất vì contract semantic/social sai kiểu. Nguyên tắc mới rất đơn giản:

> **Public text là availability contract. Soft metadata hỏng không được quyền giết một câu trả lời hợp lệ.**

## Thay đổi chính

1. `PUBLIC_REPLY_CORE_SCHEMA` chỉ bắt buộc `should_speak`, `text`, `speech_text`.
2. `semantic_frame`, `assistant_act`, `social_plan`, `self_capability_claims` trở thành soft metadata ở boundary của public writer. Chúng vẫn được sanitize/normalize ở runtime nếu model trả về.
3. `PUBLIC_REPLY_SCHEMA` cũ vẫn được giữ cho compatibility/test và các đường semantic đầy đủ khác.
4. Prompt direct-user được rút gọn. Writer ưu tiên trả câu dùng được trước, không phải điền cả cây social plan mới được phép nói.
5. JSONL worker validate nested type đệ quy. Trường hợp object bắt buộc mà model trả boolean sẽ bị phát hiện sớm.
6. Parser malformed JSON ưu tiên cứu public text kể cả khi payload đã có metadata.
7. `_compat_public_envelope()` dùng text đã cứu để tạo `assistant_act` mặc định. Metadata sai kiểu không làm text biến mất.
8. Direct public writer có deadline riêng qua `ERIS_PUBLIC_WRITER_DEADLINE_SEC` (mặc định 24 giây, không vượt deadline semantic tổng).
9. Bổ sung metric: `public_writer_provider_ms`, `public_writer_content_chars`, `public_writer_contract_valid`, `public_writer_text_salvaged`, `public_writer_usable_text`, `public_writer_wording_retry`, `public_writer_fallback`, `public_writer_commit_ms`.

## Nghiệm thu Windows

Chạy `run_eris.bat` với cùng probe + 8 lượt liveliness trước đây. Sau đó:

```bat
py tools\public_writer_recovery_v6_acceptance.py logs\eris_observability.jsonl --last-seconds 300
```

Gate tối thiểu cho bài test 9 lượt:

```text
runtime errors:                  0
usable public reply:             9/9
public_writer_fallback_total:    0
required_reply_repair fallback:  0
```

Latency không nên còn bị kéo tới 50–80 giây chỉ để nhận fallback. Nếu provider vẫn chậm, xem `public_writer_provider_ms`; nếu provider nhanh nhưng `user_turn_latency_ms` cao thì bottleneck nằm ngoài writer.

## Lưu ý

V6 không xóa semantic/social system. Nó chỉ tách **availability** khỏi **metadata completeness**. Đây là fail-soft đúng chỗ: metadata có thể degrade, nhưng public reply hợp lệ vẫn được commit.
