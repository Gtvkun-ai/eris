from __future__ import annotations

"""Worker OCR tăng dần: đổi cửa sổ/đổi pixel mới đọc, không block chat."""

import hashlib
import json
import os
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Protocol

import mss
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from .active_window_provider import ActiveWindowProvider
from .change_detector import ScreenChangeDetector
from .evidence_models import ActiveWindowInfo, ScreenTextBlock, ScreenTextSnapshot
from .windows_uia_reader import WindowsUIAReader


class SnapshotSink(Protocol):
    def publish(self, snapshot: ScreenTextSnapshot) -> None: ...


class _OCRBackend:
    name = "none"
    available = False
    def read(self, image: Image.Image, *, window_title: str, captured_at: float) -> tuple[ScreenTextBlock, ...]:
        return ()


class _RapidOCRBackend(_OCRBackend):
    name = "rapidocr"
    def __init__(self) -> None:
        self.available = False
        try:
            import numpy as np  # type: ignore
            from rapidocr_onnxruntime import RapidOCR  # type: ignore
            self._np = np
            self._engine = RapidOCR()
            self.available = True
        except Exception:
            self.available = False

    def read(self, image: Image.Image, *, window_title: str, captured_at: float) -> tuple[ScreenTextBlock, ...]:
        if not self.available:
            return ()
        try:
            result, _elapsed = self._engine(self._np.asarray(image.convert("RGB")))
        except Exception:
            return ()
        blocks: list[ScreenTextBlock] = []
        for index, item in enumerate(result or []):
            try:
                box, raw_text, raw_score = item
                text = re.sub(r"\s+", " ", str(raw_text or "")).strip()
                score = float(raw_score or 0.0)
                if len(text) < 2 or score < 0.35:
                    continue
                xs = [int(point[0]) for point in box]; ys = [int(point[1]) for point in box]
                bounds = (min(xs), min(ys), max(xs)-min(xs), max(ys)-min(ys))
                digest = hashlib.sha1(f"rapidocr|{window_title}|{index}|{text}".encode("utf-8", "ignore")).hexdigest()[:16]
                blocks.append(ScreenTextBlock(digest, text[:1000], "ocr", max(0.35, min(0.92, score)), window_title, captured_at, bounds))
            except Exception:
                continue
        return tuple(blocks)


class _PytesseractBackend(_OCRBackend):
    name = "pytesseract"
    def __init__(self) -> None:
        self.available = False
        try:
            import pytesseract  # type: ignore
            command = os.getenv("ERIS_TESSERACT_CMD", "").strip() or shutil.which("tesseract")
            if command:
                pytesseract.pytesseract.tesseract_cmd = command
                self._module = pytesseract
                self.available = True
        except Exception:
            self.available = False

    def read(self, image: Image.Image, *, window_title: str, captured_at: float) -> tuple[ScreenTextBlock, ...]:
        if not self.available:
            return ()
        lang = os.getenv("ERIS_SCREEN_OCR_LANG", "vie+eng").strip() or "eng"
        config = os.getenv("ERIS_SCREEN_OCR_TESSERACT_CONFIG", "--psm 6")
        try:
            data = self._module.image_to_data(image, lang=lang, config=config, output_type=self._module.Output.DICT)
        except Exception:
            try:
                data = self._module.image_to_data(image, lang="eng", config=config, output_type=self._module.Output.DICT)
            except Exception:
                return ()
        lines: dict[tuple[int, int, int], list[tuple[str, float, tuple[int, int, int, int]]]] = {}
        count = len(data.get("text", []))
        for index in range(count):
            text = str(data["text"][index] or "").strip()
            if not text:
                continue
            try:
                conf = float(data["conf"][index]) / 100.0
            except Exception:
                conf = 0.55
            if conf < 0.30:
                continue
            key = (int(data.get("block_num", [0] * count)[index]), int(data.get("par_num", [0] * count)[index]), int(data.get("line_num", [0] * count)[index]))
            bounds = (int(data["left"][index]), int(data["top"][index]), int(data["width"][index]), int(data["height"][index]))
            lines.setdefault(key, []).append((text, conf, bounds))
        blocks: list[ScreenTextBlock] = []
        for key, words in lines.items():
            text = re.sub(r"\s+", " ", " ".join(word for word, _, _ in words)).strip()
            if len(text) < 2:
                continue
            confidence = sum(conf for _, conf, _ in words) / max(1, len(words))
            left = min(b[0] for _, _, b in words); top = min(b[1] for _, _, b in words)
            right = max(b[0] + b[2] for _, _, b in words); bottom = max(b[1] + b[3] for _, _, b in words)
            digest = hashlib.sha1(f"ocr|{window_title}|{key}|{text}".encode("utf-8", "ignore")).hexdigest()[:16]
            blocks.append(ScreenTextBlock(digest, text[:1000], "ocr", max(0.35, min(0.90, confidence)), window_title, captured_at, (left, top, right-left, bottom-top)))
        return tuple(blocks)


def _choose_ocr_backend() -> _OCRBackend:
    preferred = os.getenv("ERIS_SCREEN_OCR_BACKEND", "auto").strip().lower() or "auto"
    candidates = []
    if preferred in {"auto", "rapidocr"}:
        candidates.append(_RapidOCRBackend())
    if preferred in {"auto", "pytesseract", "tesseract"}:
        candidates.append(_PytesseractBackend())
    for candidate in candidates:
        if candidate.available:
            return candidate
    return _OCRBackend()


class IncrementalScreenTextWorker:
    def __init__(self, sink: SnapshotSink, *, logger=None) -> None:
        self.sink = sink
        self.logger = logger
        self.enabled = os.getenv("ERIS_SCREEN_TEXT_INDEX_ENABLED", "1").strip().lower() not in {"0", "false", "off", "no"}
        self.poll_sec = max(0.5, float(os.getenv("ERIS_SCREEN_TEXT_POLL_SEC", "1.2") or 1.2))
        self.min_ocr_interval = max(0.5, float(os.getenv("ERIS_SCREEN_OCR_MIN_INTERVAL_SEC", "1.5") or 1.5))
        self.full_refresh_sec = max(3.0, float(os.getenv("ERIS_SCREEN_OCR_FULL_REFRESH_SEC", "15") or 15.0))
        self.window_provider = ActiveWindowProvider()
        self.uia_reader = WindowsUIAReader()
        self.detector = ScreenChangeDetector(threshold=float(os.getenv("ERIS_SCREEN_CHANGE_THRESHOLD", "0.025") or 0.025))
        self.backend: _OCRBackend | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._revision = 0
        self._last_ocr_at = 0.0
        self._last_full_at = 0.0
        self._last_blocks: tuple[ScreenTextBlock, ...] = ()
        self.cache_path = self._resolve_cache_path()

    def _resolve_cache_path(self) -> Path:
        explicit = os.getenv("ERIS_LIGHT_OCR_CACHE_PATH", "").strip()
        if explicit:
            return Path(explicit).expanduser()
        local = os.getenv("LOCALAPPDATA", "").strip()
        if local:
            return Path(local) / "ERIS" / "ocr_state.json"
        return Path.cwd() / "ocr_state.json"

    def start(self) -> None:
        if not self.enabled or (self._thread is not None and self._thread.is_alive()):
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="ERIS-ScreenTextIndex", daemon=True)
        self._thread.start()
        if self.logger:
            self.logger.info("[screen text] worker started backend=lazy-auto poll=%.1fs", self.poll_sec)

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)

    def _capture(self, window: ActiveWindowInfo) -> Image.Image | None:
        try:
            with mss.mss() as sct:
                if window.bounds:
                    left, top, width, height = window.bounds
                    raw = sct.grab({"left": left, "top": top, "width": width, "height": height})
                else:
                    raw = sct.grab(sct.monitors[0])
            return Image.frombytes("RGB", raw.size, raw.rgb)
        except Exception:
            return None

    def _prepare(self, image: Image.Image) -> Image.Image:
        gray = ImageOps.grayscale(image)
        gray = ImageOps.autocontrast(gray)
        gray = ImageEnhance.Contrast(gray).enhance(1.35)
        gray = gray.filter(ImageFilter.SHARPEN)
        if gray.width < 1400:
            scale = min(2.0, 1400.0 / max(1, gray.width))
            gray = gray.resize((int(gray.width * scale), int(gray.height * scale)), Image.Resampling.LANCZOS)
        return gray

    def _merge_blocks(self, uia: tuple[ScreenTextBlock, ...], ocr: tuple[ScreenTextBlock, ...]) -> tuple[ScreenTextBlock, ...]:
        merged: list[ScreenTextBlock] = []
        seen: set[str] = set()
        for block in (*uia, *ocr):
            key = re.sub(r"\W+", " ", block.text.lower()).strip()
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(block)
        return tuple(merged[:240])

    def _run(self) -> None:
        while not self._stop.is_set():
            started = time.time()
            window = self.window_provider.get()
            privacy_blocked = self.uia_reader.is_sensitive(window.title) and not self.uia_reader.allow_sensitive
            image = None if privacy_blocked else self._capture(window)
            errors: list[str] = []
            changed_ratio = 0.0
            uia_blocks = () if privacy_blocked else self.uia_reader.read(window)
            ocr_blocks: tuple[ScreenTextBlock, ...] = ()
            should_ocr = False
            if image is not None:
                change = self.detector.inspect(image, key=f"{window.hwnd}:{window.title}")
                changed_ratio = change.ratio
                now = time.time()
                should_ocr = bool(change.changed and (now - self._last_ocr_at) >= self.min_ocr_interval)
                if (now - self._last_full_at) >= self.full_refresh_sec:
                    should_ocr = True
                if should_ocr and self.backend is None:
                    self.backend = _choose_ocr_backend()
                    if self.logger:
                        self.logger.info("[screen text] OCR backend resolved=%s", self.backend.name if self.backend.available else "uia_only")
                if should_ocr and self.backend is not None and self.backend.available:
                    target = image
                    if change.roi and not change.full_refresh and (now - self._last_full_at) < self.full_refresh_sec:
                        target = image.crop(change.roi)
                    ocr_blocks = self.backend.read(self._prepare(target), window_title=window.title, captured_at=now)
                    self._last_ocr_at = now
                    if change.full_refresh or (now - self._last_full_at) >= self.full_refresh_sec:
                        self._last_full_at = now
            elif not privacy_blocked:
                errors.append("capture_unavailable")

            blocks = self._merge_blocks(uia_blocks, ocr_blocks)
            if not blocks and not privacy_blocked:
                blocks = self._last_blocks
            elif blocks:
                self._last_blocks = blocks
            self._revision += 1
            snapshot = ScreenTextSnapshot(window=window, blocks=blocks, captured_at=time.time(), changed_ratio=changed_ratio, revision=self._revision, backend=self.backend.name if self.backend is not None and self.backend.available else "uia_only", privacy_blocked=privacy_blocked, errors=tuple(errors))
            self.sink.publish(snapshot)
            self._write_cache(snapshot)
            elapsed = time.time() - started
            self._stop.wait(max(0.05, self.poll_sec - elapsed))

    def _write_cache(self, snapshot: ScreenTextSnapshot) -> None:
        if snapshot.privacy_blocked:
            return
        text = "\n".join(block.text for block in snapshot.blocks[:80])[:6000]
        payload = {
            "source": "accessibility" if any(b.source == "uia" for b in snapshot.blocks) else "ocr",
            "confidence": snapshot.best_confidence,
            "visible_text": text,
            "title": snapshot.window.title,
            "captured_at": snapshot.captured_at,
            "updated_at": snapshot.captured_at,
            "backend": snapshot.backend,
        }
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.cache_path.with_suffix(self.cache_path.suffix + ".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.cache_path)
        except Exception:
            pass
