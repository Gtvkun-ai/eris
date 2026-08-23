# Kịch bản video guide Eris Pool Setup

Độ dài nên giữ 3-5 phút. Không giải thích kỹ thuật. Chỉ quay thao tác.

## Video 1 - Cài key lần đầu

Lời thoại:

> Mở thư mục Eris. Nếu là lần đầu dùng, chạy `ErisSetup.exe`.
> Vào tab `Setup`, bấm `Open user guide` hoặc `Open secrets file`.
> File `config\secrets.json` hiện ra. Đây là nơi điền key. Không sửa file example.

Cảnh quay:

1. Double click `ErisSetup.exe`.
2. Tab `Setup`.
3. Bấm `Open secrets file`.
4. Notepad mở `config\secrets.json`.
5. Chỉ vào các dòng `ERIS_DS_*_API_KEY`, `FIREBASE_API_KEY`, `ERIS_TTS_ENABLED`.

Kết:

> Nếu chưa dùng voice, để `ERIS_TTS_ENABLED` bằng `0`. Giờ chuyển sang tạo DeepSeek pool.

## Video 2 - DeepSeek Pool

Lời thoại:

> Trong Setup, bấm `Open Pool UI` ở mục DeepSeek. Trình duyệt sẽ tự mở web quản lý pool.
> Mật khẩu mặc định là `123456`.
> Mỗi pool là một Gateway Key. Eris dùng các role: companion, surface, seed, executive, curator.

Cảnh quay:

1. Bấm `DeepSeek pool UI`.
2. Đăng nhập `123456`.
3. Bấm `+ Tạo mới`.
4. Đặt tên pool `companion`.
5. Bấm `Tạo mới`.
6. Bấm `Nhập CSV`.
7. Chọn CSV có cột `email,password`.
8. Bấm `Check nick sống`.
9. Lặp nhanh/nhảy cảnh cho `surface`, `seed`, `executive`, `curator`.
10. Quay lại Setup, bấm `Apply role keys`.
11. Mở `config\secrets.json` cho thấy các dòng key đã được điền, nhưng che key khi quay video.

Nhắc trên màn hình:

```text
Tên pool phải đúng:
companion, surface, seed, executive, curator, observer, critic, inner, style
```

## Video 3 - ElevenLabs Pool

Lời thoại:

> ElevenLabs cần hai thứ. Một là `FIREBASE_API_KEY` điền trong `secrets.json`. Hai là refresh token của từng account, dán vào web ElevenLabs Pool.

Cảnh quay:

1. Bấm `Open secrets file`.
2. Chỉ vào dòng `FIREBASE_API_KEY`.
3. Bấm `Open ElevenLabs Pool`.
4. Bấm `+ Thêm Account`.
5. Dán refresh token vào `Refresh Token(s)`.
6. Bấm `Lưu & Đồng Bộ Quota`.
7. Nhìn bảng account hiện quota.

Nhắc trên màn hình:

```text
Không có FIREBASE_API_KEY thì sync quota ElevenLabs sẽ báo thiếu Firebase.
Mỗi refresh token là một account.
```

## Video 4 - Chạy Eris

Lời thoại:

> Khi DeepSeek pool đã có key và account sống, quay lại Manager bấm `Start Eris`. Nếu chỉ cần kiểm tra nhanh thì bấm `Smoke test`.

Cảnh quay:

1. Manager tab `Runtime`.
2. Bấm `Smoke test`.
3. Bấm `Start Eris`.
4. Nếu có lỗi, mở `run_doctor.bat`.

Kết:

> Gặp lỗi thiếu key thì chạy lại `Secrets setup`. Gặp lỗi pool thì mở lại Pool UI và check nick sống.
