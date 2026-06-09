# -*- coding: utf-8 -*-
"""debug_render.py — ``DebugRender`` + ``Phase2Run`` (stage debug, R12).

Sinh **bản ghi người-đọc-được** (human-readable) cho một lần chạy pipeline
Phase 2 hoàn chỉnh. Đây là stage debug cuối cùng: không thay đổi dữ liệu, chỉ
trình bày lại các artifact đã thu thập để con người soi.

### ``Phase2Run`` — hình dạng đầu vào của ``DebugRender.render``

Chưa có kiểu ``Phase2Run`` chính thức trong pipeline, nên module này định nghĩa
một dataclass nhẹ gom đúng những gì cần render:

- ``frame_id: str | None`` — ``frame_id`` của ``WorkspaceFrame`` được xử lý;
  ``None`` nếu không xác định (R12.6).
- ``stage_debugs: list[StageDebug]`` — các ``StageDebug`` thu thập qua từng
  stage của pipeline (đầu ra thứ hai của mỗi stage), theo thứ tự pipeline.
- ``result: Phase2Result | None`` — kết quả cuối (``surfaced`` / ``withheld`` /
  ``decisions``) của ``SurfaceMeaningPolicy``; có thể ``None`` nếu pipeline dừng
  sớm trước khi surface.

### Hợp đồng render

- **R12.1** — mỗi stage in kèm ``Confidence`` / ``Ambiguity`` / ``Overread_Risk``
  (mỗi giá trị ∈ [0,1]); giá trị ``None`` → in ``unavailable`` (R12.5), vẫn
  render tiếp các stage còn lại.
- **R12.2** — mọi kết luận bị **suppressed** hoặc **withheld** đều in kèm lý do:
  lấy từ ``result.withheld`` (kèm ``brake_reason`` / overread-suppressed của
  ``EvaluatedConclusion``) và từ ``result.decisions`` (``SurfaceDecision.reason``).
- **R12.4 / R12.6** — ghi ``frame_id`` của run; không có → ``frame_id unavailable``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .contracts import (
    EvaluatedConclusion,
    Phase2Result,
    StageDebug,
    SurfaceDecision,
)


__all__ = ["Phase2Run", "DebugRender"]


def _render_metric(value: float | None) -> str:
    """Render một chỉ số: ``f"{value:.3f}"`` khi có giá trị, else ``"unavailable"`` (R12.5)."""

    if value is None:
        return "unavailable"
    return f"{value:.3f}"


@dataclass(slots=True)
class Phase2Run:
    """Ảnh chụp nhẹ một lần chạy pipeline Phase 2 phục vụ debug render.

    Xem docstring module cho ý nghĩa từng field.
    """

    frame_id: str | None = None
    stage_debugs: list[StageDebug] = field(default_factory=list)
    result: Phase2Result | None = None


class DebugRender:
    """Render một ``Phase2Run`` thành chuỗi nhiều dòng người-đọc-được (R12)."""

    __slots__ = ()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def render(self, run: Phase2Run) -> str:
        """Trả bản ghi debug nhiều dòng cho ``run`` (R12.1, R12.2, R12.4–R12.6)."""

        lines: list[str] = []

        # --- R12.4 / R12.6: frame_id của run ---
        frame_id = getattr(run, "frame_id", None)
        if frame_id is None:
            lines.append("frame_id unavailable")
        else:
            lines.append(f"frame_id: {frame_id}")

        # --- R12.1 / R12.5: từng stage kèm ba chỉ số ---
        lines.append("")
        lines.append("=== Stages ===")
        stage_debugs = getattr(run, "stage_debugs", None) or []
        if not stage_debugs:
            lines.append("(no stage debug recorded)")
        for sd in stage_debugs:
            lines.extend(self._render_stage(sd))

        # --- R12.2: kết luận suppressed / withheld kèm lý do ---
        lines.append("")
        lines.append("=== Suppressed / Withheld conclusions ===")
        lines.extend(self._render_withheld(getattr(run, "result", None)))

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Stage rendering (R12.1, R12.5)
    # ------------------------------------------------------------------
    def _render_stage(self, sd: StageDebug) -> list[str]:
        """Render một ``StageDebug``: tên stage + ba chỉ số + missing fields / notes."""

        out: list[str] = []
        stage = getattr(sd, "stage", "") or "<unknown stage>"
        out.append(f"- {stage}")
        out.append(f"    Confidence:    {_render_metric(getattr(sd, 'confidence', None))}")
        out.append(f"    Ambiguity:     {_render_metric(getattr(sd, 'ambiguity', None))}")
        out.append(f"    Overread_Risk: {_render_metric(getattr(sd, 'overread_risk', None))}")

        missing = getattr(sd, "missing_fields", None) or []
        if missing:
            out.append(f"    missing_fields: {', '.join(str(m) for m in missing)}")

        notes = getattr(sd, "notes", None) or []
        for note in notes:
            out.append(f"    note: {note}")
        return out

    # ------------------------------------------------------------------
    # Suppressed / withheld rendering (R12.2)
    # ------------------------------------------------------------------
    def _render_withheld(self, result: Phase2Result | None) -> list[str]:
        """Render mọi kết luận bị giữ lại / chặn kèm lý do.

        Gom hai nguồn lý do:
          * ``result.withheld`` — các ``EvaluatedConclusion`` bị giữ lại, kèm
            cờ ``overread_suppressed`` và ``brake_reason`` của brake.
          * ``result.decisions`` — ``SurfaceDecision`` ghi ``status`` + ``reason``
            cho từng kết luận; ta in các quyết định ``withheld``.
        """

        if result is None:
            return ["(no Phase2Result available)"]

        out: list[str] = []

        # Lý do từ SurfaceDecision (R10.5 → R12.2).
        decisions = getattr(result, "decisions", None) or []
        withheld_decisions = [
            d for d in decisions if getattr(d, "status", "") == "withheld"
        ]
        if withheld_decisions:
            out.append("withheld decisions:")
            for d in withheld_decisions:
                out.extend(self._render_decision(d))

        # Chi tiết overread-suppressed từ EvaluatedConclusion trong withheld set.
        withheld = getattr(result, "withheld", None) or []
        if withheld:
            out.append("withheld conclusions:")
            for ev in withheld:
                out.extend(self._render_evaluated(ev))

        if not out:
            out.append("(none)")
        return out

    @staticmethod
    def _render_decision(decision: SurfaceDecision) -> list[str]:
        """Render một ``SurfaceDecision`` bị withheld kèm lý do (R12.2)."""

        cid = getattr(decision, "conclusion_id", "") or "<unknown>"
        reason = getattr(decision, "reason", "") or "(no reason)"
        return [f"  - {cid}: {reason}"]

    @staticmethod
    def _render_evaluated(ev: EvaluatedConclusion) -> list[str]:
        """Render một ``EvaluatedConclusion`` bị giữ lại, phản chiếu overread-suppress.

        Bao gồm ``brake_reason`` + ``metric_name``/``metric_value`` (R8.4) và
        ``original_confidence`` đã được giữ lại cho debug (R8.5).
        """

        conclusion = getattr(ev, "conclusion", None)
        cid = ""
        for attr in ("hypothesis_id", "intent_id", "inference_id"):
            value = getattr(conclusion, attr, None)
            if value:
                cid = str(value)
                break
        if not cid:
            cid = "<unknown>"

        suppressed = getattr(ev, "overread_suppressed", False)
        reason = getattr(ev, "brake_reason", "") or "(no brake reason)"
        metric_name = getattr(ev, "metric_name", "") or ""
        metric_value = getattr(ev, "metric_value", 0.0)
        original = getattr(ev, "original_confidence", None)
        current = getattr(ev, "confidence", None)

        detail = (
            f"  - {cid}: overread_suppressed={suppressed}, reason={reason}"
        )
        if metric_name:
            detail += f", {metric_name}={metric_value:.3f}"
        detail += (
            f", confidence={_render_metric(current)}"
            f" (original={_render_metric(original)})"
        )
        return [detail]
