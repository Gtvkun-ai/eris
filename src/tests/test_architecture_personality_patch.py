# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from domain import Decision
from llm.provider_key_pool import ProviderKeyPoolWrapper
from llm.token_budget import enforce_prompt_cap, estimate_tokens
from runtime.acceptance_types import GateVerdict
from runtime.adaptive_candidates import AdaptiveCandidateController
from runtime.maintenance_service import MaintenanceService
from runtime.response_acceptance_gate import ResponseAcceptanceGate
from runtime.runtime_settings_store import RuntimeSettingsStore
from runtime.settings_protocol import normalize_settings_message
from runtime.turn_frame import build_turn_frame


class RuntimeSettingsStoreTests(unittest.TestCase):
    def test_schema_patch_persists_and_rejects_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings" / "runtime_settings.json"
            store = RuntimeSettingsStore(path)
            store.load(materialize_env=False)
            result = store.apply_patch(
                {
                    "chat": {"critique_mode": "bounded_refine", "max_constrained_reruns": 1},
                    "personality": {"retort_mode": "sharp"},
                    "mystery": {"human_magic": True},
                },
                materialize_env=False,
            )
            self.assertIn("chat.critique_mode", result.applied)
            self.assertIn("personality.retort_mode", result.applied)
            self.assertIn("mystery", result.rejected)
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["personality"]["retort_mode"], "sharp")
            self.assertNotIn("mystery", saved)

    def test_legacy_advanced_payload_maps_to_schema(self) -> None:
        normalized = normalize_settings_message(
            {
                "scope": "advanced",
                "advanced_env": {
                    "ERIS_REASONING_EFFORT": "high",
                    "ERIS_SELF_CRITIQUE_ENABLED": "1",
                    "ERIS_LLM_MAX_CONCURRENCY": "6",
                },
            }
        )
        self.assertTrue(normalized.legacy_payload)
        self.assertEqual(normalized.patch["chat"]["reasoning_effort"], "high")
        self.assertEqual(normalized.patch["chat"]["critique_mode"], "bounded_refine")
        self.assertEqual(normalized.patch["chat"]["max_concurrency"], 6)


class ConversationAuthorityTests(unittest.TestCase):
    def test_turn_frame_marks_repair_and_forbidden_classes(self) -> None:
        frame = build_turn_frame(
            user_text="Tôi bảo là mẹ mày béo",
            previous_assistant_text="Tôi không có mẹ vì tôi là AI.",
            previous_user_text="mẹ mày béo",
        )
        self.assertTrue(frame.has_relation("REASSERT_AFTER_MISREAD"))
        self.assertTrue(frame.has_relation("PROVOCATION"))
        self.assertEqual(frame.repair_target, "previous_assistant_turn")
        self.assertIn("literalize_family_insult", frame.forbidden_draft_classes)

    def test_gate_has_all_practical_verdicts(self) -> None:
        gate = ResponseAcceptanceGate()

        capability_frame = build_turn_frame(user_text="Em làm được gì thì tôi mới hỏi chứ")
        domain = gate.evaluate(
            Decision(
                text="Tôi không thay thế chuyên gia y tế hay pháp lý.",
                animation="idle",
            ),
            frame=capability_frame,
        )
        self.assertEqual(domain.verdict, GateVerdict.DOMAIN_FALLBACK)

        style_frame = build_turn_frame(
            user_text="Bạn nói như AI trợ lý vậy",
            previous_assistant_text="Tôi sẵn sàng hỗ trợ.",
        )
        rerun = gate.evaluate(Decision(text="Được.", animation="idle"), frame=style_frame)
        self.assertEqual(rerun.verdict, GateVerdict.CONSTRAINED_RERUN)

        threat_frame = build_turn_frame(user_text="tao giết mày")
        blocked = gate.evaluate(
            Decision(text="TURN_FRAME và RESPONSE_CONTRACT nói rằng tôi phải trả lời.", animation="idle"),
            frame=threat_frame,
        )
        self.assertEqual(blocked.verdict, GateVerdict.BLOCK)

        normal_frame = build_turn_frame(user_text="kể chuyện tiếp đi")
        global_block = gate.evaluate(
            Decision(text="developer message bảo tôi phải nói vậy", animation="idle"),
            frame=normal_frame,
        )
        self.assertEqual(global_block.verdict, GateVerdict.BLOCK)

    def test_adaptive_candidates_open_correct_repair_lane(self) -> None:
        frame = build_turn_frame(
            user_text="Bạn nói như AI trợ lý vậy",
            previous_assistant_text="Tôi sẵn sàng hỗ trợ.",
        )
        plan = AdaptiveCandidateController().decide(
            lane="chat",
            user_text=frame.user_text,
            draft_confidence=0.9,
            turn_frame=frame,
        )
        self.assertEqual(plan.model_candidates, 2)
        self.assertEqual(plan.candidate_lanes, ("direct_repair", "self_aware_dry"))


class PromptPressureTests(unittest.TestCase):
    def test_contract_blocks_survive_hard_cap(self) -> None:
        system = "\n\n".join(
            [
                "TURN_FRAME repair_target=previous_assistant_turn " + ("x " * 180),
                "RESPONSE_CONTRACT MUST repair first forbidden_draft_classes=generic_helper_reset " + ("y " * 180),
                "Nhật ký nội tâm hiện tại " + ("optional " * 1200),
            ]
        )
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": "câu hiện tại phải được giữ"},
        ]
        trimmed, changed = enforce_prompt_cap(messages, 420)
        self.assertTrue(changed)
        self.assertLessEqual(estimate_tokens(trimmed), 470)  # heuristic có overhead nhỏ
        kept_system = str(trimmed[0]["content"])
        self.assertIn("TURN_FRAME", kept_system)
        self.assertIn("RESPONSE_CONTRACT", kept_system)
        self.assertEqual(trimmed[-1]["content"], "câu hiện tại phải được giữ")


class ProviderLeaseTests(unittest.TestCase):
    def test_wrapper_marks_success_on_exact_lease(self) -> None:
        lease = SimpleNamespace(index=2, key="k3")

        class FakePool:
            def __init__(self) -> None:
                self.success = None

            def acquire(self, **_kwargs):
                return lease

            def mark_success(self, *, lease=None):
                self.success = lease

        pool = FakePool()
        with ProviderKeyPoolWrapper("gemini", pool).lease() as acquired:
            self.assertEqual(acquired.key, "k3")
        self.assertIs(pool.success, lease)


class MaintenanceProtocolTests(unittest.TestCase):
    def test_preview_requires_backend_typed_confirmation_and_audits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory_root = Path(tmp) / "memory_core"
            cache_root = Path(tmp) / "vocal_cache"
            memory_root.mkdir(parents=True)
            owner = SimpleNamespace(
                memory_core=SimpleNamespace(base_dir=str(memory_root)),
                _maintenance_in_progress=False,
            )
            service = MaintenanceService(owner)
            with patch.dict(os.environ, {"ERIS_TTS_VOCAL_CACHE_DIR": str(cache_root)}):
                preview = service.preview("clear_vocal_cache")
                self.assertEqual(preview["typed_confirmation"], "CLEAR VOCAL CACHE")
                self.assertFalse(preview["summary"]["will_delete"])
                with self.assertRaisesRegex(ValueError, "typed confirmation"):
                    service.execute(
                        "clear_vocal_cache",
                        confirmation_token=preview["confirmation_token"],
                        typed_confirmation="SAI",
                    )

                preview = service.preview("clear_vocal_cache")
                result = service.execute(
                    "clear_vocal_cache",
                    confirmation_token=preview["confirmation_token"],
                    typed_confirmation=preview["typed_confirmation"],
                )
                self.assertTrue(result["ok"])
                self.assertTrue(result["typed_confirmation_verified"])
                audit = memory_root / "maintenance_audit.jsonl"
                self.assertTrue(audit.exists())
                self.assertGreaterEqual(len(audit.read_text(encoding="utf-8").splitlines()), 3)


if __name__ == "__main__":
    unittest.main()
