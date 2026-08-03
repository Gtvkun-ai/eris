# Sửa lỗi Architecture C bootstrap

## Triệu chứng

`vision.py` khởi động xong các worker nhưng thoát ngay, sau đó launcher tự khởi động lại liên tục.

Lỗi gốc trong log:

```text
RandomChatSeedAffinityStore.snapshot() got an unexpected keyword argument 'now'
[architecture C] bootstrap failed; legacy runtime has been removed
```

## Nguyên nhân

Bootstrap gọi `random_chat_seed_store.snapshot(now=runtime_clock())`, nhưng method
`RandomChatSeedAffinityStore.snapshot()` cũ không nhận keyword `now`.

Đây là lỗi contract giữa bootstrap và seed store. Vì legacy runtime đã bị xóa,
TypeError trong bước ghi health details làm toàn bộ Architecture C thất bại.

## Thay đổi

1. `RandomChatSeedAffinityStore.snapshot()` nhận `now` dạng keyword-only để giữ
   contract đồng nhất với runtime clock. Snapshot vẫn chỉ đọc và không tự persist.
2. Thêm `_safe_health_snapshot()` tại bootstrap. Telemetry snapshot lỗi sẽ được
   log và trả metadata lỗi, không còn được phép hạ toàn bộ runtime chính.
3. Áp dụng boundary an toàn cho seed store, seed reservoir và social agenda.
4. Thêm regression test cho đúng lỗi `snapshot(now=...)` và test containment khi
   một component snapshot ném exception.

## Kiểm tra

- 93/93 test liên quan Architecture C, seed, reservoir và bootstrap: đạt.
- 698 test khả dụng toàn repo: đạt.
- Compile toàn bộ 670 file Python: đạt.
- 3 test module và 5 test case phụ thuộc `tools/*` không có trong archive gốc,
  nên không thể chạy. Đây không phải lỗi do bản vá này.
