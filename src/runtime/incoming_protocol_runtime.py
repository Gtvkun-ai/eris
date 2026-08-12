# -*- coding: utf-8 -*-
"""Inbound protocol dispatch and non-chat control messages.

Extracted from RuntimeCoordinator so the composition root stops owning every policy.
"""
from __future__ import annotations

import os
import time

from runtime.stage_protocol import is_stage_inbound_type


class IncomingProtocolRuntimeMixin:
    """Coordinator-facing mixin with no independent lifecycle."""

    def _ensure_transport_boundary(self):
        boundary = getattr(self, "transport_boundary", None)
        if boundary is None:
            from runtime.transport_boundary import RuntimeTransportBoundary

            boundary = RuntimeTransportBoundary(
                self.transport,
                health_registry=getattr(self, "subsystem_health_registry", None),
                logger=getattr(self, "logger", None),
            )
            self.transport_boundary = boundary
        return boundary

    def _send_runtime_json(
        self,
        payload: dict,
        *,
        channel: str = "control",
        required: bool = False,
    ) -> bool:
        return bool(
            self._ensure_transport_boundary().send_json(
                payload, channel=channel, required=required
            )
        )

    def _ensure_incoming_dispatcher(self):
        dispatcher = getattr(self, "incoming_dispatcher", None)
        if dispatcher is None:
            from runtime.incoming_dispatcher import IncomingMessageDispatcher

            dispatcher = IncomingMessageDispatcher(
                self,
                settings=getattr(getattr(self, "runtime_policy_settings", None), "protocol", None),
            )
            self.incoming_dispatcher = dispatcher
        return dispatcher

    def _handle_incoming(self, msg: dict):
        return self._ensure_incoming_dispatcher().dispatch(msg)


    def _handle_panel_state_ack(self, msg: dict) -> None:
        """Nhận receipt từ Body cho lane panel.

        UDP không đảm bảo giao hàng. Trước Phase 7, Brain chỉ biết đã ``sendto``
        chứ không biết C# có parse được hay không, nên panel trống vẫn có thể bị
        ghi thành “gửi thành công”. Receipt này biến visibility thành evidence.
        """

        packet_id = str(msg.get("packet_id", "") or "").strip()
        complete = bool(msg.get("complete", False))
        has_private_mind = bool(msg.get("has_private_mind", False))
        has_emotion = bool(msg.get("has_emotion", False))
        has_depth = bool(msg.get("has_depth", False))
        try:
            sent_at = float(msg.get("sent_at", 0.0) or 0.0)
        except (TypeError, ValueError):
            sent_at = 0.0
        latency_ms = max(0.0, (time.time() - sent_at) * 1000.0) if sent_at > 0 else 0.0
        obs = getattr(self, "observability", None)
        if obs is not None:
            obs.increment(
                "panel_state_ack_total",
                tags={"complete": str(complete).lower()},
                fields={
                    "packet_id": packet_id,
                    "has_private_mind": has_private_mind,
                    "has_emotion": has_emotion,
                    "has_depth": has_depth,
                },
            )
            if complete:
                obs.increment("panel_state_ack_complete_total", fields={"packet_id": packet_id})
            if latency_ms > 0:
                obs.observe("panel_state_ack_latency_ms", latency_ms, fields={"packet_id": packet_id})
        phase7 = getattr(self, "phase7_validation", None)
        if phase7 is not None:
            try:
                phase7.mark_scenario(
                    "panel_delivery",
                    passed=complete,
                    detail=(
                        f"packet={packet_id}; private_mind={has_private_mind}; "
                        f"emotion={has_emotion}; depth={has_depth}; latency_ms={latency_ms:.1f}"
                    ),
                )
            except Exception as exc:
                logger = getattr(self, "logger", None)
                debug = getattr(logger, "debug", None)
                if callable(debug):
                    debug("[phase7] panel delivery mark failed: %s", exc)


    def _handle_memory_panel_request(self, msg: dict) -> None:
        """Đọc/sửa Living User Memory qua panel Godot.

        Handler luôn gửi snapshot mới sau thao tác để UI không phải tự đoán state.
        Payload nhạy cảm bị loại tại runtime, không chỉ ẩn bằng CSS phía client.
        """
        from runtime.living_user_panel import handle_memory_panel_request

        request_id = str(msg.get("request_id", "") or "")
        kernel = getattr(self, "memory_kernel", None)
        living_user = getattr(kernel, "living_user", None)
        result = handle_memory_panel_request(
            living_user,
            msg,
            cleanup_service=getattr(self, "memory_gc_service", None),
        )
        self._send_runtime_json({
            "type": "memory_panel_ack",
            "parse_mode": "memory_panel_ack",
            "should_speak": False,
            "request_id": request_id,
            "action": str(msg.get("action", "snapshot") or "snapshot"),
            "status": result.status,
            "message": result.message,
            "memory_panel": result.payload,
        }, channel="memory_panel")


    def _handle_phase7_validation_control(self, msg: dict) -> None:
        """Control protocol nhỏ để chạy Phase 7 trên máy thật qua UDP 4243."""

        action = str(msg.get("action", "status") or "status").strip().lower()
        manager = getattr(self, "phase7_validation", None)
        result: dict[str, object]
        try:
            manager_disabled = not bool(
                getattr(getattr(manager, "config", None), "production_validation_enabled", False)
            )
            if action == "start" and self.observability is not None and (manager is None or manager_disabled):
                from dataclasses import replace
                from runtime.hardening_config import HardeningConfig
                from runtime.phase7_validation import Phase7ValidationManager

                base_cfg = getattr(self, "hardening_config", None) or HardeningConfig.load()
                cfg = replace(base_cfg, production_validation_enabled=True)
                manager = Phase7ValidationManager(
                    observability=self.observability,
                    provider_health_fn=self.provider_health_snapshot,
                    rollout_status_fn=(
                        self.rollout_controller.status
                        if self.rollout_controller is not None and callable(getattr(self.rollout_controller, "status", None))
                        else (lambda: {})
                    ),
                    config=cfg,
                    release_id=str(msg.get("release_id", "") or os.getenv("ERIS_RELEASE_ID", "") or ""),
                    environment_fn=self._phase7_environment_snapshot,
                )
                self.phase7_validation = manager
            if manager is None:
                raise RuntimeError("phase7_validation_unavailable")

            if action == "start":
                state = manager.start(validation_id=str(msg.get("validation_id", "") or ""))
                result = state.to_dict() if state is not None else manager.status()
            elif action == "mark":
                manager.mark_scenario(
                    str(msg.get("scenario", "") or ""),
                    passed=bool(msg.get("passed", False)),
                    turn_id=str(msg.get("turn_id", "") or ""),
                    detail=str(msg.get("detail", "") or ""),
                )
                result = manager.status()
            elif action == "finalize":
                report = manager.finalize(reason=str(msg.get("reason", "manual") or "manual"))
                result = report.to_dict() if report is not None else manager.status()
            else:
                result = manager.status()
            status = "ok"
        except Exception as exc:
            status = "error"
            result = {"error": type(exc).__name__, "message": str(exc)[:240]}
        self._send_runtime_json({
            "type": "phase7_validation_ack",
            "parse_mode": "phase7_validation_ack",
            "should_speak": False,
            "action": action,
            "status": status,
            "phase7_validation": result,
        }, channel="phase7")


    def _phase7_environment_snapshot(self) -> dict[str, object]:
        import platform
        import sys

        tts = getattr(self, "tts_engine", None)
        signature = ""
        if tts is not None and callable(getattr(tts, "cache_signature", None)):
            try:
                signature = str(tts.cache_signature() or "")
            except Exception:
                signature = ""
        try:
            from runtime.hardening_config import HardeningConfig
            hardening = HardeningConfig.load().to_dict()
        except Exception:
            hardening = {}
        return {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "runtime_session_id": str(getattr(self, "runtime_session_id", "") or ""),
            "tts_signature": signature,
            "provider_health": self.provider_health_snapshot(),
            "subsystem_health": (
                getattr(self, "subsystem_health_registry").snapshot(include_events=False)
                if callable(getattr(getattr(self, "subsystem_health_registry", None), "snapshot", None))
                else {}
            ),
            "hardening_config": hardening,
            "runtime_diagnostics": (
                self.runtime_diagnostics.snapshot(include_events=False)
                if callable(getattr(getattr(self, "runtime_diagnostics", None), "snapshot", None))
                else {}
            ),
        }


    def _handle_maintenance_catalog(self, msg: dict | None = None) -> None:
        """Trả danh sách thao tác Danger Zone và thống kê cache hiện tại."""

        service = getattr(self, "maintenance_service", None)
        try:
            payload = service.catalog() if service is not None else {"actions": [], "error": "maintenance_service_unavailable"}
            self._send_runtime_json({
                "type": "maintenance_catalog_ack",
                "parse_mode": "maintenance_catalog_ack",
                "should_speak": False,
                "maintenance_catalog_ack": payload,
            })
        except Exception as exc:
            self.logger.warning("[maintenance] catalog failed: %s", exc)


    def _handle_maintenance_request(self, msg: dict) -> None:
        """Preview hoặc thực thi command Danger Zone.

        Protocol hai bước ngăn một click lệch tay xóa state ngay lập tức:
        ``dry_run=true`` trả manifest + token; Body chỉ execute bằng token đó.
        """

        service = getattr(self, "maintenance_service", None)
        request_id = str(msg.get("request_id", "") or "")
        action = str(msg.get("action", "") or "").strip().lower()
        dry_run = str(msg.get("type", "") or "") != "maintenance_execute" and bool(msg.get("dry_run", True))
        options = msg.get("options") if isinstance(msg.get("options"), dict) else {}
        try:
            if service is None:
                raise RuntimeError("maintenance_service_unavailable")
            if dry_run:
                result = service.preview(action, options=options)
                envelope_type = "maintenance_preview_ack"
                field = "maintenance_preview_ack"
            else:
                token = str(msg.get("confirmation_token", "") or "")
                typed_confirmation = str(msg.get("typed_confirmation", "") or "")
                result = service.execute(
                    action, confirmation_token=token,
                    typed_confirmation=typed_confirmation, options=options,
                )
                envelope_type = "maintenance_execute_ack"
                field = "maintenance_execute_ack"
            self._send_runtime_json({
                "type": envelope_type,
                "parse_mode": envelope_type,
                "should_speak": False,
                field: {
                    "request_id": request_id,
                    "protocol_phase": "preview" if dry_run else "execute",
                    **result,
                },
            })
        except Exception as exc:
            self.logger.warning("[maintenance] request action=%s dry_run=%s failed: %s", action, dry_run, exc)
            self._send_runtime_json({
                "type": "maintenance_execute_ack",
                "parse_mode": "maintenance_execute_ack",
                "should_speak": False,
                "maintenance_execute_ack": {
                    "request_id": request_id,
                    "action": action,
                    "ok": False,
                    "changed": [],
                    "warnings": [],
                    "errors": [str(exc)[:320]],
                    "backup_dir": "",
                },
            }, channel="maintenance")


__all__ = ["IncomingProtocolRuntimeMixin"]
