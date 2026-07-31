# -*- coding: utf-8 -*-
"""Chess.com bridge service wired to the durable engagement runtime."""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Mapping

from runtime.cognition.normalization import normalize_vi
from runtime.engagements import EvidenceBinding
from runtime.subsystem_health import FailureKind, SubsystemHealthRegistry

from .contracts import BoardSnapshot, ChessObservation, ChessObservationPhase
from .engine import Position, analyze
from .tracker import ChessGameTracker
from .surface import ChessSurfaceState, chess_turn_relevant
from .companion_policy import build_companion_signal


class ChessCompanionService:
    # Contract generic cho StructuredEvidenceProvider. Chat pipeline chỉ biết
    # đây là một nguồn structured state, không cần hard-code ChessCompanionService.
    structured_source_id = "chess_bridge"
    engagement_kind = "chess"

    def __init__(
        self,
        engagement_runtime,
        *,
        host: str = "127.0.0.1",
        port: int = 8765,
        token: str = "",
        analysis_depth: int = 2,
        direct_move_rate: float = 0.18,
        max_body_bytes: int = 65536,
        logger: Any | None = None,
        health_registry: SubsystemHealthRegistry | None = None,
        wake_callback: Any | None = None,
        clock=None,
    ) -> None:
        self.engagement_runtime = engagement_runtime
        self.host = str(host or "127.0.0.1")
        self.port = int(port)
        self.token = str(token or "")
        self.max_body_bytes = max(1024, int(max_body_bytes))
        self.logger = logger
        self.health_registry = health_registry
        self.wake_callback = wake_callback if callable(wake_callback) else None
        self.clock = clock or time.time
        self.tracker = ChessGameTracker(depth=analysis_depth, direct_move_rate=direct_move_rate)
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._last_snapshot_summary: dict[str, Any] = {}
        self._last_wakeup_reason = ""

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> "ChessCompanionService":
        with self._lock:
            if self.running:
                return self
            service = self

            class Handler(BaseHTTPRequestHandler):
                server_version = "ERISChessBridge/1.0"

                def log_message(self, fmt, *args):
                    if service.logger is not None:
                        try:
                            service.logger.debug("[chess-bridge] " + fmt, *args)
                        except (AttributeError, TypeError, ValueError, RuntimeError):
                            pass

                def _headers(self, status: int = 200):
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Access-Control-Allow-Origin", "https://www.chess.com")
                    self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Eris-Bridge-Token")
                    self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
                    self.end_headers()

                def _json(self, payload: Mapping[str, Any], status: int = 200):
                    self._headers(status)
                    self.wfile.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))

                def do_OPTIONS(self):
                    self._headers(204)

                def do_GET(self):
                    if self.path.rstrip("/") in {"", "/health", "/v1/chess/health"}:
                        self._json(service.diagnostics())
                    else:
                        self._json({"ok": False, "error": "not_found"}, 404)

                def do_POST(self):
                    if self.path.rstrip("/") != "/v1/chess/snapshot":
                        self._json({"ok": False, "error": "not_found"}, 404)
                        return
                    if service.token and self.headers.get("X-Eris-Bridge-Token", "") != service.token:
                        self._json({"ok": False, "error": "unauthorized"}, 401)
                        return
                    try:
                        length = int(self.headers.get("Content-Length", "0") or 0)
                    except ValueError:
                        self._json({"ok": False, "error": "invalid_length"}, 400)
                        return
                    if length <= 0 or length > service.max_body_bytes:
                        self._json({"ok": False, "error": "body_size"}, 413)
                        return
                    try:
                        payload = json.loads(self.rfile.read(length).decode("utf-8"))
                        if not isinstance(payload, Mapping):
                            raise ValueError("payload must be an object")
                        observation = service.handle_snapshot(payload)
                    except (ValueError, TypeError, json.JSONDecodeError) as exc:
                        service._failure(exc, degraded=False)
                        self._json({"ok": False, "error": str(exc)[:160]}, 400)
                        return
                    except (OSError, RuntimeError, KeyError, AttributeError) as exc:
                        service._failure(exc, degraded=True)
                        self._json({"ok": False, "error": "bridge_failure"}, 500)
                        return
                    self._json({"ok": True, "observation": observation.to_event_payload()})

            self._server = ThreadingHTTPServer((self.host, self.port), Handler)
            self.port = int(self._server.server_address[1])
            self._server.daemon_threads = True
            self._thread = threading.Thread(
                target=self._server.serve_forever,
                name="eris-chess-bridge",
                daemon=True,
            )
            self._thread.start()
            self._success({"host": self.host, "port": self.port})
            if self.logger is not None:
                try:
                    self.logger.info("[chess-bridge] listening on http://%s:%s", self.host, self.port)
                except (AttributeError, TypeError, ValueError, RuntimeError):
                    pass
            return self

    def stop(self) -> None:
        with self._lock:
            server, thread = self._server, self._thread
            self._server = None
            self._thread = None
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        if self.health_registry is not None:
            self.health_registry.mark_stopped("chess.bridge")

    shutdown = stop
    close = stop

    def handle_snapshot(self, payload: Mapping[str, Any]) -> ChessObservation:
        snapshot = BoardSnapshot.from_mapping(payload)
        observation = self.tracker.observe(snapshot)
        received_at = float(self.clock())
        now = snapshot.captured_at or received_at
        phase = getattr(getattr(observation, "phase", ""), "value", getattr(observation, "phase", ""))
        phase = str(phase or "unknown")
        with self._lock:
            self._last_snapshot_summary = {
                "game_id": snapshot.game_id,
                "mode": observation.mode.value,
                "phase": phase,
                "board_fen": snapshot.board_fen,
                "side_to_move": observation.side_to_move,
                "move_number": observation.move_number,
                "ply": snapshot.ply,
                "last_move_uci": observation.last_move_uci,
                "last_move_san": str(getattr(observation, "last_move_san", "") or ""),
                "suggested_move_uci": (
                    observation.suggestion.uci if observation.suggestion is not None else ""
                ),
                "suggested_move_san": (
                    observation.suggestion.san if observation.suggestion is not None else ""
                ),
                "evaluation_cp": getattr(observation, "evaluation_cp", None),
                "evaluation_label": str(getattr(observation, "evaluation_label", "") or ""),
                "evaluation_swing_cp": getattr(observation, "evaluation_swing_cp", None),
                "move_quality": str(getattr(observation, "move_quality", "") or ""),
                "hint_focus": str(getattr(observation, "hint_focus", "") or ""),
                "result": str(getattr(observation, "result", "") or ""),
                "orientation": str(getattr(snapshot, "orientation", "") or ""),
                "captured_at": snapshot.captured_at or received_at,
                # Freshness phải dựa trên lúc bridge NHẬN snapshot. Timestamp từ
                # extension có thể dùng clock khác hoặc bị serialize theo ms.
                "received_at": received_at,
                "engagement_id": "",
            }
        if self.logger is not None:
            try:
                self.logger.info(
                    "[chess-bridge] snapshot game=%s mode=%s phase=%s move=%s turn=%s last=%s suggestion=%s",
                    snapshot.game_id,
                    observation.mode.value,
                    phase,
                    observation.move_number,
                    observation.side_to_move,
                    observation.last_move_uci or "-",
                    (
                        observation.suggestion.uci
                        if observation.suggestion is not None
                        else "-"
                    ),
                )
            except (AttributeError, TypeError, ValueError, RuntimeError):
                pass
        binding = EvidenceBinding(
            app="chess.com",
            surface_key=f"chess.com:{snapshot.game_id}",
            resource_id=f"chess:{snapshot.platform}:{snapshot.game_id}",
            tags=("chess", snapshot.platform, observation.mode.value),
        )
        engagement = self._resolve_engagement(binding=binding, now=now)
        with self._lock:
            if self._last_snapshot_summary.get("game_id") == snapshot.game_id:
                self._last_snapshot_summary["engagement_id"] = engagement.engagement_id
        companion_signal = build_companion_signal(
            observation,
            snapshot,
            engagement.domain_state,
        )
        event_payload = observation.to_event_payload()
        event_payload.update(companion_signal.to_dict())
        evidence_refs = (f"chesscom:{snapshot.game_id}:{snapshot.ply}",)
        emitted: list[str] = []
        with self._lock:
            if self._last_snapshot_summary.get("game_id") == snapshot.game_id:
                self._last_snapshot_summary.update(companion_signal.to_dict())

        # Nếu người dùng đã ra lệnh xem cờ trước khi mở bàn, phải nối snapshot
        # vào đúng engagement đó thay vì âm thầm tạo một task cờ thứ hai.
        board_seen_before = bool(engagement.domain_state.get("board_seen", False))
        if not board_seen_before:
            emitted.append("chess.board_detected")

        if observation.game_started:
            emitted.append("chess.game_started")
        if observation.last_move_uci:
            emitted.append("chess.move_played")
        elif not emitted and observation.phase is ChessObservationPhase.ACTIVE:
            emitted.append("chess.position_changed")
        elif not emitted and observation.phase is ChessObservationPhase.WAITING_FOR_START:
            emitted.append("chess.board_ready")
        if observation.game_over:
            emitted.append("chess.game_over")

        # Một snapshot có thể vừa đánh dấu bắt đầu vừa chứa nước đi đầu tiên.
        # Ghi đủ cả hai event để planner biết "ván bắt đầu" và "nước vừa đi".
        for kind in dict.fromkeys(emitted):
            updated = self.engagement_runtime.emit_domain_event(
                kind,
                payload=event_payload,
                engagement_id=engagement.engagement_id,
                binding=binding,
                evidence_refs=evidence_refs,
                now=now,
            )
            if updated is not None:
                engagement = updated

        wake_events = tuple(
            kind for kind in dict.fromkeys(emitted)
            if kind in {"chess.board_detected", "chess.game_started", "chess.move_played", "chess.game_over"}
        )
        # The bridge always records structured state, but it only wakes the public
        # initiative loop for a meaningful chess beat. Routine moves remain
        # available to chat without turning ERIS into a move-by-move alarm clock.
        if wake_events and companion_signal.should_wake:
            self._wake_autonomous(
                game_id=snapshot.game_id,
                move_number=observation.move_number,
                events=wake_events,
            )

        self._success({
            "game_id": snapshot.game_id,
            "mode": observation.mode.value,
            "phase": observation.phase.value,
            "events": emitted,
        })
        return observation

    def _wake_autonomous(self, *, game_id: str, move_number: int, events: tuple[str, ...]) -> None:
        callback = self.wake_callback
        if callback is None:
            return
        reason = f"chess_event:{events[-1]}:game={game_id}:move={move_number}"
        self._last_wakeup_reason = reason
        try:
            callback(reason)
        except Exception as exc:  # noqa: BLE001 - callback boundary must not break bridge HTTP
            if self.logger is not None:
                try:
                    self.logger.warning("[chess-bridge] autonomous wake failed: %s", exc)
                except (AttributeError, TypeError, ValueError, RuntimeError):
                    pass

    def _resolve_engagement(self, *, binding: EvidenceBinding, now: float):
        """Nối bridge vào task cờ người dùng đã tạo, nếu task đó còn chưa có bàn.

        Trước bản vá, câu "xem tôi đánh cờ" tạo một engagement không có
        ``resource_id``; snapshot sau đó lại tạo engagement thứ hai vì resource
        mới không khớp. Hậu quả là một task cứ hỏi "bàn đâu", task kia lại tự
        bình luận. Tách đôi như vậy rất sáng tạo, nhưng không hữu ích.
        """

        active = tuple(self.engagement_runtime.registry.active())
        for item in active:
            if item.kind == "chess" and item.evidence_binding.resource_id == binding.resource_id:
                return item

        foreground = self.engagement_runtime.registry.foreground()
        candidates = [
            item for item in active
            if item.kind == "chess" and not item.evidence_binding.meaningful
        ]
        target = foreground if foreground in candidates else (candidates[0] if candidates else None)
        if target is not None:
            return self.engagement_runtime.bind_engagement(
                target.engagement_id,
                binding,
                now=now,
                source="chess_bridge",
            ) or target

        return self.engagement_runtime.ensure_profile(
            "chess",
            objective="Đồng hành cùng người dùng trong ván cờ hiện tại",
            binding=binding,
            now=now,
            source="chess_bridge",
        )


    def active_engagement_id(self) -> str:
        """Trả engagement id đang active, độc lập với độ tươi của FEN."""

        with self._lock:
            engagement_id = str(self._last_snapshot_summary.get("engagement_id", "") or "").strip()
        if not engagement_id:
            return ""
        try:
            engagement = self.engagement_runtime.registry.get(engagement_id)
        except Exception:
            return ""
        return engagement_id if engagement is not None and bool(getattr(engagement, "active", False)) else ""

    def is_engagement_active(self) -> bool:
        """Phiên cờ còn active không đồng nghĩa snapshot FEN vẫn còn tươi."""

        return bool(self.active_engagement_id())

    def is_state_fresh(self, *, max_age_seconds: float = 30.0) -> bool:
        """Kiểm riêng freshness của board snapshot, không dùng nó làm lifecycle."""

        with self._lock:
            item = dict(self._last_snapshot_summary)
        received_at = float(item.get("received_at", 0.0) or 0.0)
        board_fen = str(item.get("board_fen", "") or "").strip()
        if not board_fen or not received_at:
            return False
        age = max(0.0, float(self.clock()) - received_at)
        return age <= max(0.5, float(max_age_seconds))

    def matches_turn(self, user_text: str) -> bool:
        """Nhận ngôn ngữ cờ tự nhiên; câu UI thuần vẫn để vision xử lý."""

        return chess_turn_relevant(
            user_text,
            engagement_active=self.is_engagement_active(),
        )

    def current_surface_state(self) -> dict[str, Any]:
        """Snapshot typed bất biến dùng chung cho chat và autonomous Surface."""

        with self._lock:
            item = dict(self._last_snapshot_summary)
        return ChessSurfaceState.from_mapping(item).to_dict()

    def diagnostics(self) -> dict[str, Any]:
        with self._lock:
            last_snapshot = dict(self._last_snapshot_summary)
        return {
            "ok": True,
            "running": self.running,
            "host": self.host,
            "port": self.port,
            "token_required": bool(self.token),
            "last_snapshot": last_snapshot,
            "last_wakeup_reason": self._last_wakeup_reason,
        }

    def current_grounding_evidence(
        self,
        *,
        max_age_seconds: float = 30.0,
        relevant_to_turn: bool = False,
    ) -> tuple[dict[str, object], ...]:
        """Xuất snapshot cờ tươi thành provenance chính thức cho chat grounding.

        Đây là state có cấu trúc từ extension, vì vậy nó đáng tin hơn việc bắt
        vision nhìn lại cùng một bàn cờ. ``relevant_to_turn`` chỉ quyết định vai
        trò primary/ambient; snapshot vẫn được đưa vào context khi engagement
        đang hoạt động để giữ continuity giữa các lượt.
        """

        with self._lock:
            item = dict(self._last_snapshot_summary)
        board_fen = str(item.get("board_fen", "") or "").strip()
        received_at = float(item.get("received_at", 0.0) or 0.0)
        age = max(0.0, float(self.clock()) - received_at) if received_at else float("inf")
        if not board_fen or age > max(0.5, float(max_age_seconds)):
            return ()

        typed = ChessSurfaceState.from_mapping(item)
        game_id = typed.game_id or "unknown"
        move_number = typed.move_number
        phase = typed.phase or "unknown"
        side_to_move = typed.side_to_move or "unknown"
        last_move = typed.last_move_uci or "-"
        suggestion = typed.suggested_move_uci or "-"
        if relevant_to_turn and suggestion == "-":
            # Tỷ lệ direct_move_rate chỉ điều khiển việc ERIS tự buột miệng gợi ý
            # trong autonomous. Khi user hỏi thẳng “nên đánh gì”, phải phân tích
            # ngay từ FEN hiện tại, không trả lời khai cuộc chung chung như sách
            # nhập môn bị thất lạc trang.
            try:
                turn = "w" if side_to_move in {"white", "w"} else "b"
                ply = max(0, (move_number - 1) * 2 + (1 if turn == "b" else 0))
                position = Position.from_board_fen(board_fen, turn=turn, ply=ply)
                candidates = analyze(position, depth=self.tracker.depth, top_n=1)
                if candidates:
                    suggestion = candidates[0][0].uci
                    item["suggested_move_uci"] = suggestion
                    typed = ChessSurfaceState.from_mapping(item)
            except Exception as exc:  # noqa: BLE001 - evidence provider phải degrade yên
                if self.logger is not None:
                    try:
                        self.logger.debug("[chess-bridge] on-demand suggestion failed: %s", exc)
                    except Exception:
                        pass
        claim = (
            "Chess board snapshot: "
            f"phase={phase}; side_to_move={side_to_move}; move_number={move_number}; "
            f"last_move={last_move}; suggested_move={suggestion}; board_fen={board_fen}"
        )
        return ({
            "id": f"chess:{game_id}:{move_number}",
            "source": self.structured_source_id,
            "evidence_kind": "structured_runtime",
            "engagement_kind": self.engagement_kind,
            "engagement_active": self.is_engagement_active(),
            "state_fresh": True,
            "claim": claim,
            # State typed là nguồn chính; claim text chỉ giữ để log/plugin cũ.
            "state": typed.to_dict(),
            "event_fingerprint": typed.event_fingerprint("chess.snapshot"),
            "confidence": 1.0,
            "grounded": True,
            "stale": False,
            "captured_at": float(item.get("captured_at", received_at) or received_at),
            "received_at": received_at,
            "relevant_to_turn": bool(relevant_to_turn),
            "role": "primary_candidate" if relevant_to_turn else "ambient",
            "engagement_id": str(item.get("engagement_id", "") or ""),
            "game_id": game_id,
            "phase": phase,
            "board_fen": board_fen,
            "side_to_move": side_to_move,
            "move_number": move_number,
            "last_move_uci": "" if last_move == "-" else last_move,
            "suggested_move_uci": "" if suggestion == "-" else suggestion,
            "tags": [
                "chess",
                "board",
                "extension",
                "structured_sensor",
                "direct_sensor",
            ],
        },)

    def _success(self, details: Mapping[str, Any]) -> None:
        if self.health_registry is not None:
            self.health_registry.record_success("chess.bridge", details=dict(details))

    def _failure(self, exc: BaseException, *, degraded: bool) -> None:
        if self.health_registry is not None:
            self.health_registry.record_failure(
                "chess.bridge",
                exc,
                kind=FailureKind.INVALID_EXTERNAL_DATA if not degraded else FailureKind.PROGRAMMER_ERROR,
                degraded=degraded,
            )
        if self.logger is not None:
            try:
                self.logger.warning("[chess-bridge] %s", exc)
            except (AttributeError, TypeError, ValueError, RuntimeError):
                pass


__all__ = ["ChessCompanionService"]
