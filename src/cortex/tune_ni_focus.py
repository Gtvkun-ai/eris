import argparse
import json
import os
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable

from .ni import DEFAULT_FOCUS_BIAS


# Prior trung lập cho trọng số kênh, dùng LÀM FALLBACK khi log drift không đủ
# dữ liệu để học (tương quan rỗng). Bản ni.py mới đã bỏ mô hình chấm điểm cũ nên
# không còn export CHANNEL_WEIGHTS; tool tuning offline này tự giữ default riêng.
# Tên kênh khớp OrientationSignal.channels (xem orientation_context.py).
CHANNEL_WEIGHTS: dict[str, float] = {
    "intent_confidence": 1.0,
    "relation_confidence": 1.0,
    "active_goal_strength": 1.0,
    "goal_intervention_permission": 1.0,
    "fragmentation": 1.0,
    "idle_ambiguity": 1.0,
    "lexical_fallback": 1.0,
}


@dataclass
class DriftSample:
    focus_kind: str
    raw_similarity: float
    drift_score: float
    should_raise_guard: bool
    channels: dict[str, float]

# _load_samples là một hàm để nạp các mẫu drift từ một tệp JSONL. 
# Mỗi dòng trong tệp được kỳ vọng là một đối tượng JSON chứa thông tin về focus_kind, 
# raw_similarity, drift_score, should_raise_guard và channels. Hàm này sẽ đọc từng dòng, 
# phân tích cú pháp JSON, và trích xuất các trường cần thiết để tạo thành một danh sách các 
# DriftSample. Nếu tệp không tồn tại hoặc có lỗi trong quá trình đọc/giải mã JSON, 
# hàm sẽ xử lý ngoại lệ và bỏ qua các dòng không hợp lệ.
def _load_samples(path: str) -> list[DriftSample]:
    samples: list[DriftSample] = []
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Không tìm thấy tệp mẫu drift: {path}")

    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue

            focus_kind = str(payload.get("focus_kind") or "unknown")
            try:
                raw_similarity = float(payload.get("raw_similarity", 0.0) or 0.0)
            except (TypeError, ValueError):
                raw_similarity = 0.0
            try:
                drift_score = float(payload.get("drift_score", 0.0) or 0.0) # Nếu trường drift_score không có hoặc không hợp lệ, mặc định là 0.0
            except (TypeError, ValueError):
                drift_score = 0.0

            should_raise_guard = bool(payload.get("should_raise_guard"))
            # Nếu trường should_raise_guard không có, suy luận từ drift_score theo ngưỡng Ni hiện tại.
            if "should_raise_guard" not in payload:
                should_raise_guard = drift_score >= 0.55

            channels_raw = payload.get("channels") or {}
            channels: dict[str, float] = {}
            if isinstance(channels_raw, dict):
                for name, value in channels_raw.items():
                    try:
                        channels[str(name)] = float(value or 0.0)
                    except (TypeError, ValueError):
                        continue

            samples.append(
                DriftSample(
                    focus_kind=focus_kind,
                    raw_similarity=raw_similarity,
                    drift_score=drift_score,
                    should_raise_guard=should_raise_guard,
                    channels=channels,
                )
            )

    return samples

# _fit_bias_scale là một hàm để tìm bias và scale tốt nhất để điều chỉnh điểm số 
# raw_similarity sao cho phù hợp với nhãn mục tiêu (should_raise_guard).
# Hàm này thực hiện hồi quy tuyến tính đơn giản để tìm bias và scale sao cho điểm số 
# sau điều chỉnh (scale * raw_similarity + bias) càng gần với TARGET_ON_GOAL khi 
# should_raise_guard là True và càng gần với TARGET_OFF_GOAL khi should_raise_guard là False.
def _fit_bias_scale(xs: Iterable[float], targets: Iterable[float]) -> tuple[float, float]:
    xs_list = list(xs)
    ys_list = list(targets)
    n = len(xs_list)
    if n == 0:
        return 1.0, 0.0

    mean_x = sum(xs_list) / n
    mean_y = sum(ys_list) / n
    var_x = sum((x - mean_x) ** 2 for x in xs_list)
    if var_x <= 1e-8:
        return 1.0, mean_y - mean_x

    cov_xy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs_list, ys_list))
    scale = cov_xy / var_x
    bias = mean_y - scale * mean_x

    # Giới hạn một chút để tránh giá trị cực đoan.
    if scale < 0.2: 
        scale = 0.2 # Nếu scale quá thấp, điều chỉnh sẽ không đủ mạnh để phân biệt on_goal/off_goal, nên đặt ngưỡng tối thiểu là 0.2.
    if scale > 3.0:
        scale = 3.0
    if bias < -0.8:
        bias = -0.8
    if bias > 0.8:
        bias = 0.8
    return scale, bias


def tune_focus_bias(samples: list[DriftSample], min_samples: int = 20) -> dict[str, dict[str, float]]:
    by_kind: dict[str, list[DriftSample]] = defaultdict(list)
    for sample in samples:
        by_kind[sample.focus_kind].append(sample) # Phân loại các mẫu drift theo focus_kind để có thể tune bias/scale riêng cho từng loại cửa sổ hoạt động.

    # Mục tiêu đơn giản: nếu không raise guard => similarity sau điều chỉnh nên khoảng ~0.8,
    # nếu raise guard => similarity sau điều chỉnh nên khoảng ~0.2.
    TARGET_ON_GOAL = 0.8
    TARGET_OFF_GOAL = 0.2

    result: dict[str, dict[str, float]] = {}
    for kind, items in by_kind.items():
        if len(items) < min_samples:
            continue

        xs: list[float] = []
        ys: list[float] = []
        for s in items:
            xs.append(s.raw_similarity)
            ys.append(TARGET_OFF_GOAL if s.should_raise_guard else TARGET_ON_GOAL)

        scale, bias = _fit_bias_scale(xs, ys)
        result[kind] = {"bias": bias, "scale": scale}

    return result


def tune_channel_weights(samples: list[DriftSample]) -> dict[str, float]:
    # Tính tầm quan trọng kênh dựa trên tương quan đơn giản với nhãn on_goal/off_goal.
    # Kênh nào cao khi on_goal và thấp khi off_goal sẽ có trọng số cao hơn.
    per_channel_values: dict[str, list[tuple[float, float]]] = defaultdict(list)

    TARGET_ON_GOAL = 1.0
    TARGET_OFF_GOAL = 0.0

    for s in samples:
        target = TARGET_OFF_GOAL if s.should_raise_guard else TARGET_ON_GOAL
        for name, score in s.channels.items():
            per_channel_values[name].append((score, target))

    import math

    importance: dict[str, float] = {}
    for name, pairs in per_channel_values.items():
        if len(pairs) < 10:
            continue
        xs = [p[0] for p in pairs]
        ys = [p[1] for p in pairs]
        n = len(xs)
        mean_x = sum(xs) / n
        mean_y = sum(ys) / n
        cov_xy = sum((x - mean_x) * (y - mean_y) for x, y in pairs)
        var_x = sum((x - mean_x) ** 2 for x in xs) # Nếu biến thiên của kênh quá thấp, nó sẽ không hữu ích để phân biệt on_goal/off_goal, nên bỏ qua.
        var_y = sum((y - mean_y) ** 2 for y in ys) # Nếu biến thiên của nhãn quá thấp (ví dụ nếu tất cả đều on_goal hoặc off_goal), thì cũng không có gì để học, nên bỏ qua.
        if var_x <= 1e-8 or var_y <= 1e-8:
            continue
        corr = cov_xy / math.sqrt(var_x * var_y)
        if corr <= 0.0:
            continue
        importance[name] = corr

    if not importance:
        return dict(CHANNEL_WEIGHTS)

    total = sum(importance.values())
    if total <= 0.0:
        return dict(CHANNEL_WEIGHTS)

    return {name: value / total for name, value in importance.items()}


def _load_existing_config(path: str) -> dict[str, Any]:
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def _save_json(path: str, data: Any) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=4)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Tuning nhẹ ni_focus_config.json và (tùy chọn) CHANNEL_WEIGHTS "
            "dựa trên log drift thực tế (JSONL)."
        )
    )
    parser.add_argument(
        "--samples",
        default="ni_drift_samples.jsonl",
        help="Đường dẫn tới file JSONL chứa mẫu drift (mỗi dòng là một JSON).",
    )
    parser.add_argument(
        "--config",
        default="ni_focus_config.json",
        help="Đường dẫn tới file cấu hình bias/scale sẽ được cập nhật.",
    )
    parser.add_argument(
        "--channel-weights-out",
        default="ni_channel_weights.json",
        help="Đường dẫn file JSON để ghi đề xuất CHANNEL_WEIGHTS (không ảnh hưởng runtime hiện tại).",
    )
    parser.add_argument(
        "--min-samples",
        type=int,
        default=20,
        help="Số mẫu tối thiểu mỗi focus_kind cần có để tune bias/scale.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Chỉ in kết quả ra stdout, không ghi file.",
    )

    args = parser.parse_args(argv)

    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    samples_path = args.samples
    if not os.path.isabs(samples_path):
        samples_path = os.path.join(project_root, samples_path)

    config_path = args.config
    if not os.path.isabs(config_path):
        config_path = os.path.join(project_root, config_path)

    channel_out_path = args.channel_weights_out
    if not os.path.isabs(channel_out_path):
        channel_out_path = os.path.join(project_root, channel_out_path)

    samples = _load_samples(samples_path)
    if not samples:
        raise SystemExit("Không có mẫu drift nào để học.")

    print(f"Đã nạp {len(samples)} mẫu drift từ {samples_path}.")

    new_bias_table = tune_focus_bias(samples, min_samples=args.min_samples)
    if not new_bias_table:
        print("Không đủ mẫu để tune bias/scale theo focus_kind. Giữ nguyên cấu hình hiện tại.")
    else:
        print("Đề xuất bias/scale mới:")
        for kind, cfg in sorted(new_bias_table.items()):
            print(f"  - {kind}: bias={cfg['bias']:.3f}, scale={cfg['scale']:.3f}")

    new_channel_weights = tune_channel_weights(samples)
    print("\nĐề xuất CHANNEL_WEIGHTS mới (chuẩn hóa tổng = 1.0):")
    for name, weight in sorted(new_channel_weights.items(), key=lambda x: x[0]):
        print(f"  - {name}: {weight:.3f}")

    if args.dry_run:
        print("\nDry-run: không ghi bất kỳ file cấu hình nào.")
        return

    config_data = _load_existing_config(config_path)
    if not config_data:
        # Nếu chưa có file, khởi tạo với default để dễ debug.
        config_data = {k: v for k, v in DEFAULT_FOCUS_BIAS.items()}

    for kind, cfg in new_bias_table.items():
        merged = dict(config_data.get(kind, {}))
        merged["bias"] = cfg["bias"]
        merged["scale"] = cfg["scale"]
        config_data[kind] = merged

    _save_json(config_path, config_data)
    print(f"\nĐã ghi cập nhật bias/scale vào {config_path}.")

    _save_json(channel_out_path, new_channel_weights)
    print(f"Đã ghi đề xuất CHANNEL_WEIGHTS vào {channel_out_path} (runtime hiện tại chưa tự động dùng file này).")


if __name__ == "__main__":  # pragma: no cover
    main()
