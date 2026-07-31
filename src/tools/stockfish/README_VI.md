# Nối Stockfish cho ERIS

Thư mục này **không chứa binary Stockfish**. Hãy tải bản phù hợp từ nguồn chính
thức, rồi đặt executable vào đây. Runtime tự tìm các tên phổ biến như:

- `stockfish.exe`
- `stockfish-windows-x86-64-avx2.exe`
- `stockfish-windows-x86-64.exe`
- `stockfish`

Hoặc đặt biến môi trường:

```env
ERIS_STOCKFISH_PATH=C:\duong-dan\stockfish.exe
```

Cấu hình nhẹ mặc định:

```env
ERIS_STOCKFISH_ENABLED=1
ERIS_STOCKFISH_THREADS=1
ERIS_STOCKFISH_HASH_MB=96
ERIS_STOCKFISH_MULTIPV=3
ERIS_STOCKFISH_MOVETIME_MS=180
ERIS_STOCKFISH_ON_DEMAND_MOVETIME_MS=700
```

Nếu executable chưa tồn tại hoặc process lỗi, ERIS tự rơi về engine nội bộ. Vì
vậy có thể chép source trước rồi nối Stockfish sau, đúng như một phần mềm biết
chấp nhận rằng thế giới bên ngoài đôi lúc chưa được cài đặt đầy đủ.
