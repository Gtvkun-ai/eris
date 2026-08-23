# Hướng dẫn nhanh cho người dùng Eris

Đây là bản dành cho người không dev. Cứ làm theo thứ tự này.

## 1. Mở Setup

Chạy:

```text
ErisSetup.exe
```

Nếu không thấy Setup, chạy:

```text
ErisManager.exe
```

## 2. Tạo file điền key

Trong tab `Setup`, bấm:

```text
Secrets setup
```

Nó sẽ mở `config\secrets.json`. Đây là file để điền key thật.

## 3. Cài DeepSeek pool

Trong tab `Setup` hoặc `Accounts`, bấm:

```text
DeepSeek pool UI
```

Trình duyệt sẽ mở:

```text
http://127.0.0.1:5010
```

Mật khẩu đăng nhập:

```text
123456
```

Trong web DeepSeek Pool:

1. Bấm `+ Tạo mới`.
2. Đặt `Tên Pool` đúng một trong các tên sau:

```text
companion
surface
seed
executive
curator
observer
critic
inner
```

3. Bấm `Tạo mới`.
4. Chọn pool vừa tạo.
5. Bấm `Nhập CSV`.
6. Chọn file CSV dạng:

```csv
email,password
email1@example.com,password1
email2@example.com,password2
```

Khi chay `DeepSeek pool UI`, Eris se tao san file mau:

```text
tools\whale2api\accounts.template.csv
```

Mo file nay, thay bang email/password DeepSeek that, luu lai, roi bam `Nhap CSV` trong Pool UI va chon file do.

7. Bấm `Check nick sống`.
8. Bấm `Vô hiệu nick lỗi` nếu có nick lỗi.
9. Pool UI se tu tao Gateway Key cho pool.

Sau khi tạo xong các pool, quay lại Setup/Manager và bấm:

```text
Apply DeepSeek pool keys
```

Tool này tự đọc Gateway Key trong Pool UI rồi ghi vào `config\secrets.json`.

## 4. Cài ElevenLabs pool

Trong tab `Setup` hoặc `Accounts`, bấm:

```text
ElevenLabs pool UI
```

Trình duyệt sẽ mở:

```text
http://127.0.0.1:18888
```

Trước khi sync quota ElevenLabs, cần điền trong `config\secrets.json`:

```text
FIREBASE_API_KEY
```

Mỗi tài khoản ElevenLabs cần lấy `refresh_token`. Trong web ElevenLabs Pool:

1. Bấm `+ Thêm Account`.
2. Dán `refresh_token` vào ô `Refresh Token(s)`.
3. Có thể dán nhiều token, mỗi dòng một token.
4. Bấm `Lưu & Đồng Bộ Quota`.

Nếu chưa muốn dùng giọng nói, để:

```text
ERIS_TTS_ENABLED=0
```

## 5. Chạy Eris

Sau khi đã có DeepSeek pool hoặc API key, chạy:

```text
run_eris.bat
```

Nếu chỉ muốn chạy phần brain console:

```text
run_runtime.bat
```

## 6. Khi bị lỗi thường gặp

Nếu web Pool UI không mở:

```text
run_deepseek_pool_ui.bat
run_elevenlabs_pool_ui.bat
```

Nếu thiếu key:

```text
setup_secrets.bat
```

Nếu DeepSeek Pool có pool rồi mà Eris vẫn báo thiếu key:

```text
apply_deepseek_pool_to_secrets.bat
```

Nếu acc ElevenLabs trắng:

1. Kiểm tra đã dán `refresh_token` chưa.
2. Kiểm tra `FIREBASE_API_KEY` trong `config\secrets.json`.
3. Bấm sync lại trong ElevenLabs Pool UI.
