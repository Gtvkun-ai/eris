# ERIS V49 — Stockfish UCI Adapter tùy chọn

## Mục tiêu

Bản vá này thêm một nguồn phân tích cờ đáng tin cậy hơn cho runtime mà không bắt
Stockfish trở thành dependency bắt buộc. Binary không được đóng gói trong source.
Người dùng có thể chép source trước, đặt executable sau và khởi động lại ERIS.

## Kiến trúc

```text
Chess.com extension
    -> BoardSnapshot / FEN
    -> ChessGameTracker
    -> HybridChessAnalyzer
        -> StockfishUCIAnalyzer (nếu có binary)
        -> LocalChessAnalyzer (fallback)
    -> ChessObservation có provenance
    -> Semantic Tutor / autonomous / chat / Surface
```

Stockfish chỉ phụ trách đánh giá bàn cờ và candidate moves. Tutor tiếp tục hiểu
ngữ cảnh người chơi; Governor quyết định có nên can thiệp; Surface chỉ viết lời.

## Điểm chính

- Giao tiếp UCI trực tiếp bằng `subprocess`, không thêm package Python.
- Process Stockfish được mở lười và giữ sống giữa các nước.
- Reader thread + queue giúp timeout hoạt động ổn định trên Windows.
- Hỗ trợ `Threads`, `Hash`, `MultiPV`, movetime thường và movetime khi user hỏi.
- Chuẩn hóa evaluation về góc nhìn Trắng trước khi tính swing/chất lượng nước.
- Candidate trả UCI, SAN, depth, mate và principal variation.
- Có timeout, restart sạch và cooldown khi engine ngoài lỗi.
- Không tìm thấy Stockfish thì tự rơi về engine nội bộ; bridge vẫn khởi động.
- `analysis_provider`, depth, nodes, elapsed, mate và PV được đưa vào shared chess
  state để Tutor/Surface biết provenance, không tự tưởng tượng nguồn phân tích.
- Câu hỏi trực tiếp “nên đi gì” dùng movetime on-demand dài hơn.

## Nối binary sau

Đặt executable vào:

```text
eris/tools/stockfish/stockfish.exe
```

hoặc đặt env:

```env
ERIS_STOCKFISH_PATH=C:\duong-dan\stockfish.exe
```

Sau đó khởi động lại ERIS. Diagnostics của chess bridge sẽ hiển thị provider,
path, readiness, số lượt phân tích và lỗi gần nhất.

## Cấu hình mặc định

```env
ERIS_STOCKFISH_ENABLED=1
ERIS_STOCKFISH_THREADS=1
ERIS_STOCKFISH_HASH_MB=96
ERIS_STOCKFISH_MULTIPV=3
ERIS_STOCKFISH_MOVETIME_MS=180
ERIS_STOCKFISH_ON_DEMAND_MOVETIME_MS=700
ERIS_STOCKFISH_STARTUP_TIMEOUT_SECONDS=4.0
ERIS_STOCKFISH_ANALYSIS_TIMEOUT_SECONDS=2.5
```

## Kiểm thử

- 29/29 test Stockfish + chess + Semantic Tutor trọng tâm passed.
- 599 test suite rộng passed khi bỏ test packaging vốn không thể import vì source
  đầu vào thiếu `tools.package_source`.
- 9 lỗi nền còn lại: 2 file `body/` không có, 5 module audit/report trong
  `tools/` không có và 2 test ElevenLabs bị chặn bởi quota account.
