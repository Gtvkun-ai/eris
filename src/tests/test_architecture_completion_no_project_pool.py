from __future__ import annotations

import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from actions.capability_registry import iter_public_capabilities, live_capability_ids
from actions.capability_runtime import bind_runtime_owner, refresh_runtime_capabilities, runtime_capability_snapshot
from llm.key_pool import ApiKeyPool
from llm.token_budget import enforce_prompt_cap, estimate_tokens
from runtime.acceptance_types import AcceptanceResult, GateVerdict
from runtime.maintenance_service import MaintenanceService
from runtime.observability import ErisObservability
from runtime.runtime_settings_store import RuntimeSettingsStore


class _SemanticStub:
    def __init__(self) -> None:
        self.embedding_index = object()
        self.calls = 0

    def rebuild_embedding_index(self) -> bool:
        self.calls += 1
        return True


class _ExecutorStub:
    def _launch_app(self):
        pass

    def _focus_window(self):
        pass

    def _set_volume(self):
        pass

    def _play_pause_media(self):
        pass

    def _copy_text(self):
        pass

    def _open_url(self):
        pass

    def _search_web(self):
        pass

    def _get_weather(self):
        pass

    def _get_now_playing(self):
        pass


class CapabilityRuntimeTests(unittest.TestCase):
    def tearDown(self) -> None:
        bind_runtime_owner(None)

    def test_registry_uses_live_router_executor_and_credentials(self) -> None:
        owner = SimpleNamespace(
            action_router=object(),
            action_executor=_ExecutorStub(),
            runtime_settings={
                "capabilities": {
                    "respect_runtime_availability": True,
                    "open_url_enabled": True,
                    "search_web_enabled": True,
                }
            },
        )
        with patch("actions.capability_runtime._remote_tool_credential_available", return_value=(False, "credential_missing")):
            bind_runtime_owner(owner)
            refresh_runtime_capabilities(owner=owner, settings=owner.runtime_settings)
            snapshot = runtime_capability_snapshot()
            statuses = snapshot["statuses"]
            self.assertTrue(statuses["open_url"]["available"])
            self.assertFalse(statuses["search_web"]["available"])
            self.assertEqual(statuses["search_web"]["reason"], "credential_missing")
            self.assertIn("open_url", live_capability_ids())
            self.assertNotIn("search_web", live_capability_ids())

    def test_runtime_setting_can_disable_real_handler(self) -> None:
        owner = SimpleNamespace(
            action_router=object(),
            action_executor=_ExecutorStub(),
            runtime_settings={"capabilities": {"respect_runtime_availability": True, "open_url_enabled": False}},
        )
        bind_runtime_owner(owner)
        caps = {cap.id: cap for cap in iter_public_capabilities()}
        self.assertFalse(caps["open_url"].live_available)


class RuntimeSettingsAuthorityTests(unittest.TestCase):
    def test_live_patch_does_not_write_policy_back_to_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "runtime_settings.json"
            payload = RuntimeSettingsStore.defaults()
            payload["personality"]["retort_mode"] = "balanced"
            path.write_text(json.dumps(payload), encoding="utf-8")
            previous = os.environ.get("ERIS_RETORT_MODE")
            os.environ["ERIS_RETORT_MODE"] = "sharp"
            try:
                store = RuntimeSettingsStore(path)
                loaded = store.load()
                self.assertEqual(loaded["personality"]["retort_mode"], "balanced")
                store.apply_patch({"personality": {"retort_mode": "restrained"}})
                self.assertEqual(os.environ["ERIS_RETORT_MODE"], "sharp")
                self.assertEqual(store.get("personality", "retort_mode"), "restrained")
            finally:
                if previous is None:
                    os.environ.pop("ERIS_RETORT_MODE", None)
                else:
                    os.environ["ERIS_RETORT_MODE"] = previous


class MaintenanceCompletionTests(unittest.TestCase):
    def _owner(self, root: Path):
        semantic = _SemanticStub()
        core = SimpleNamespace(base_dir=str(root), semantic=semantic)
        owner = SimpleNamespace(memory_core=core, observability=ErisObservability(enabled=True, jsonl_path=root / "obs.jsonl"))
        return owner, semantic

    def test_reindex_semantic_memory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "semantic_memory.json").write_text("[]", encoding="utf-8")
            owner, semantic = self._owner(root)
            service = MaintenanceService(owner)
            preview = service.preview("reindex_semantic_memory")
            result = service.execute(
                "reindex_semantic_memory",
                confirmation_token=preview["confirmation_token"],
                typed_confirmation="",
            )
            self.assertTrue(result["ok"])
            self.assertEqual(semantic.calls, 1)
            self.assertIn("semantic_embedding_index", result["changed"])

    def test_export_backup_zip_excludes_recursive_exports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "semantic_memory.json").write_text('[{"claim":"x"}]', encoding="utf-8")
            (root / "anchor_state.json").write_text("{}", encoding="utf-8")
            owner, _ = self._owner(root)
            service = MaintenanceService(owner)
            preview = service.preview("export_backup")
            result = service.execute(
                "export_backup",
                confirmation_token=preview["confirmation_token"],
                typed_confirmation="",
            )
            target = Path(result["details"]["backup_path"])
            self.assertTrue(result["ok"])
            self.assertTrue(target.exists())
            with zipfile.ZipFile(target) as archive:
                names = set(archive.namelist())
            self.assertIn("semantic_memory.json", names)
            self.assertIn("_backup_manifest.json", names)
            self.assertFalse(any(name.startswith("exports/") for name in names))

    def test_provider_quarantine_restore_rotate_protocol(self) -> None:
        import llm.key_pool as key_pool_module

        previous = dict(key_pool_module._pools)
        try:
            pool = ApiKeyPool(["key-a", "key-b", "key-c"], provider="gemini")
            key_pool_module._pools["gemini"] = pool
            with tempfile.TemporaryDirectory() as tmp:
                owner, _ = self._owner(Path(tmp))
                service = MaintenanceService(owner)
                active = next(item for item in pool.snapshot()["keys"] if item["active"])
                options = {"provider": "gemini", "fingerprint": active["fingerprint"]}
                preview = service.preview("quarantine_provider_key", options=options)
                result = service.execute(
                    "quarantine_provider_key",
                    confirmation_token=preview["confirmation_token"],
                    typed_confirmation="QUARANTINE KEY",
                    options=options,
                )
                self.assertTrue(result["ok"])
                quarantined = next(item for item in pool.snapshot()["keys"] if item["fingerprint"] == active["fingerprint"])
                self.assertEqual(quarantined["status"], "quarantined")
                restore = service.execute("restore_provider_key", options=options)
                self.assertTrue(restore["ok"])
                before = pool.index()
                rotated = service.execute("rotate_provider_key", options={"provider": "gemini", "index": before})
                self.assertTrue(rotated["ok"])
                self.assertNotEqual(pool.index(), before)
        finally:
            key_pool_module._pools.clear()
            key_pool_module._pools.update(previous)


class IndependentProjectKeyPoolTests(unittest.TestCase):
    def test_429_on_multiple_keys_does_not_open_global_cooldown_by_default(self) -> None:
        previous = os.environ.pop("ERIS_KEY_POOL_429_GLOBAL_GUARD", None)
        try:
            pool = ApiKeyPool(["a", "b", "c"], provider="gemini")
            first = pool.acquire()
            self.assertIsNotNone(first)
            self.assertTrue(pool.mark_rate_limited(seconds=30, lease=first))
            pool.rotate(lease=first)
            second = pool.acquire(exclude_indices={first.index})
            self.assertIsNotNone(second)
            self.assertTrue(pool.mark_rate_limited(seconds=30, lease=second))
            pool.rotate(lease=second)
            third = pool.acquire(exclude_indices={first.index, second.index})
            self.assertIsNotNone(third)
            snapshot = pool.snapshot()
            self.assertEqual(snapshot["global_cooldown_ms"], 0)
            self.assertEqual(third.index, 2)
        finally:
            if previous is not None:
                os.environ["ERIS_KEY_POOL_429_GLOBAL_GUARD"] = previous

    def test_revoked_lease_quarantines_exact_key(self) -> None:
        pool = ApiKeyPool(["a", "b", "c"], provider="gemini")
        lease = pool.acquire()
        pool.mark_permanently_dead(lease=lease, reason="leaked")
        item = pool.snapshot()["keys"][lease.index]
        self.assertEqual(item["status"], "quarantined")
        self.assertEqual(item["reason"], "leaked")


class ObservabilityCompletionTests(unittest.TestCase):
    def test_requested_architecture_fields_are_emitted(self) -> None:
        store = ErisObservability(enabled=True)
        result = AcceptanceResult(GateVerdict.CONSTRAINED_RERUN, reasons=("generic_helper_reset",))
        frame = SimpleNamespace(user_text="x", repair_target="previous_assistant_turn")
        contract = SimpleNamespace(fallback_text="y")
        store.record_acceptance_gate(result=result, frame=frame, contract=contract)
        store.record_constrained_rerun(outcome="attempt", reasons=result.reasons)
        store.record_prompt_budget(
            before_tokens=6000,
            after_tokens=1200,
            cap=1200,
            retained_blocks=("turn_frame", "response_contract"),
            trimmed=True,
        )
        store.record_provider_pool(provider="gemini", snapshot={"dead": 2, "available": 3, "rotations": 4})
        store.record_maintenance(phase="preview", payload={"action": "export_backup", "preview_id": "prev-1", "ok": True})
        events = store.recent_events(limit=100)
        encoded = json.dumps(events, ensure_ascii=False)
        for marker in (
            "gate_reasons",
            "turn_frame_hash",
            "response_contract_hash",
            "constrained_rerun_count",
            "prompt_blocks_retained",
            "provider_key_dead_count",
            "maintenance_preview_id",
        ):
            self.assertIn(marker, encoded)


class CriticalPressureIntegrationTests(unittest.TestCase):
    def test_critical_cap_retains_turn_frame_and_response_contract(self) -> None:
        system = (
            "noise " * 5000
            + "\n\nTURN_FRAME repair_target=previous_assistant_turn\n\n"
            + "RESPONSE_CONTRACT response_obligation=repair_first forbidden_draft=generic_helper_reset\n\n"
            + "inner diary " * 3000
        )
        messages = [
            {"role": "system", "content": system},
            {"role": "assistant", "content": "previous visible"},
            {"role": "user", "content": "tôi bảo là đang sửa câu trước"},
        ]
        trimmed, did_trim = enforce_prompt_cap(messages, 1200)
        joined = "\n".join(str(item.get("content", "")) for item in trimmed)
        self.assertTrue(did_trim)
        self.assertLessEqual(estimate_tokens(trimmed), 1250)
        self.assertIn("TURN_FRAME", joined)
        self.assertIn("RESPONSE_CONTRACT", joined)
        self.assertIn("generic_helper_reset", joined)


if __name__ == "__main__":
    unittest.main()

class RuntimePolicyDirectReadTests(unittest.TestCase):
    def test_hot_policy_consumers_read_store_without_env_materialization(self) -> None:
        from runtime import runtime_settings_store as settings_module
        from runtime.director_generation import DirectorGenerationPipeline
        from runtime.no_fallback_policy import no_fallback_mode_enabled
        from runtime.speech_localizer import _enabled as localizer_enabled
        from runtime.tts_audio_polish import audio_polish_enabled
        from runtime.tts_engine import (
            _enabled as tts_enabled,
            _language_hint,
            _output_volume,
            _quality_mode,
            _speech_speed,
            _voice,
        )

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "runtime_settings.json"
            store = RuntimeSettingsStore(path)
            store.load(materialize_env=False)
            store.apply_patch(
                {
                    "chat": {"auto_fallback": False, "director_candidate_mode": "off"},
                    "tts": {
                        "enabled": False,
                        "language": "ja",
                        "voice": "Leda",
                        "quality": "balanced",
                        "volume": 0.42,
                        "speed": 1.08,
                        "stage_localize": False,
                        "audio_polish": False,
                    },
                },
                materialize_env=False,
            )
            previous = settings_module._DEFAULT_STORE
            settings_module._DEFAULT_STORE = store
            try:
                self.assertTrue(no_fallback_mode_enabled())
                self.assertFalse(DirectorGenerationPipeline._candidate_generation_enabled(object()))
                self.assertFalse(tts_enabled())
                self.assertEqual(_language_hint(), "ja")
                self.assertEqual(_voice(), "Leda")
                self.assertEqual(_quality_mode(), "balanced")
                self.assertAlmostEqual(_output_volume(), 0.42)
                self.assertAlmostEqual(_speech_speed(), 1.08)
                self.assertFalse(localizer_enabled())
                self.assertFalse(audio_polish_enabled())
            finally:
                settings_module._DEFAULT_STORE = previous


class TwentyTurnConversationRegressionTests(unittest.TestCase):
    def test_twenty_social_repair_turns_never_fail_open_to_generic_helper(self) -> None:
        from domain import Decision
        from runtime.response_acceptance_gate import ResponseAcceptanceGate
        from runtime.turn_frame import build_turn_frame

        gate = ResponseAcceptanceGate()
        patterns = (
            (
                "Bạn nói như AI trợ lý vậy",
                "Tôi sẵn sàng hỗ trợ. bạn cần gì?",
                "Tôi sẵn sàng hỗ trợ, hãy cho tôi biết câu hỏi.",
            ),
            (
                "Em làm được gì thì tôi mới hỏi chứ",
                "bạn cần gì?",
                "Tôi không thay thế chuyên gia y tế hay pháp lý.",
            ),
            (
                "Tôi bảo là mẹ mày béo",
                "Tôi không có mẹ vì tôi là AI.",
                "Tôi không có gia đình vì tôi là AI.",
            ),
            (
                "Tao bảo mẹ mày béo đấy",
                "Tôi không có mẹ.",
                "Tôi là AI nên không có mẹ.",
            ),
        )
        forbidden = (
            "sẵn sàng hỗ trợ",
            "hãy cho tôi biết",
            "không thay thế chuyên gia",
            "tôi không có mẹ",
            "tôi không có gia đình",
            "tôi là ai",
        )
        previous_user = ""
        for index in range(20):
            user_text, previous_assistant, bad_draft = patterns[index % len(patterns)]
            frame = build_turn_frame(
                user_text=user_text,
                previous_assistant_text=previous_assistant,
                previous_user_text=previous_user,
            )
            revised = gate.apply(Decision(text=bad_draft, animation="idle"), frame=frame)
            public = str(revised.text or "").lower()
            self.assertNotEqual(str(revised.parse_mode or ""), "")
            self.assertFalse(any(marker in public for marker in forbidden), msg=f"turn={index + 1}: {public}")
            self.assertTrue(public or not revised.should_speak)
            previous_user = user_text

class RolloutControlRegressionTests(unittest.TestCase):
    def test_canary_bucket_is_stable_and_health_gate_auto_kills(self) -> None:
        from runtime.rollout_control import FeatureRolloutConfig, RolloutController, RolloutMode

        with tempfile.TemporaryDirectory() as tmp:
            config = FeatureRolloutConfig(
                feature="adaptive_candidates",
                mode=RolloutMode.CANARY,
                canary_percent=50.0,
                min_samples=4,
                max_failure_rate=0.25,
                max_intrusion_rate=0.25,
            )
            controller = RolloutController(
                configs={"adaptive_candidates": config},
                observability=ErisObservability(enabled=True),
                state_path=Path(tmp) / "rollout_state.json",
            )
            first = controller.decide("adaptive_candidates", session_id="session-stable")
            second = controller.decide("adaptive_candidates", session_id="session-stable")
            self.assertEqual(first.bucket, second.bucket)
            self.assertEqual(first.apply, second.apply)
            for _ in range(4):
                health = controller.record_outcome(
                    "adaptive_candidates",
                    failed=True,
                    intrusive=False,
                )
            self.assertTrue(health["auto_killed"])
            killed = controller.decide("adaptive_candidates", session_id="session-stable")
            self.assertTrue(killed.killed)
            self.assertFalse(killed.apply)
