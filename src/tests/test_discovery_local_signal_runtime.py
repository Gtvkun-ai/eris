from __future__ import annotations

import time
from dataclasses import replace
from types import SimpleNamespace

from runtime.ai_orchestrated.contracts import IntentionPlan
from runtime.ai_orchestrated.discovery import (
    DiscoveryPlan,
    DiscoveryRecord,
    DiscoveryRuntime,
    ExternalNeedGate,
)
from runtime.ai_orchestrated.identity import IdentityProfile, RelationshipIdentity


class _Logger:
    def debug(self, *_args, **_kwargs):
        pass

    def info(self, *_args, **_kwargs):
        pass

    def warning(self, *_args, **_kwargs):
        pass


class _Router:
    def plan_discovery(self, _snapshot):
        return DiscoveryPlan()


class _Tutor:
    def __init__(self):
        self.last_answer_ts = 0.0
        self.last_answer_text = ""
        self.last_question_text = ""
        self.last_research_bundle = {}
        self.last_research_thread = {}

    def search_now(self, topic, **_kwargs):
        self.last_answer_ts = time.time()
        self.last_answer_text = "Một tin công nghệ mới trong nước, đã được đối chiếu từ hai nguồn."
        self.last_question_text = topic
        self.last_research_bundle = {
            "verification": {"confidence": 0.82, "verified": True},
            "sources": [
                {"title": "Nguồn A"},
                {"title": "Nguồn B"},
            ],
        }
        self.last_research_thread = {"topic": topic}
        return self.last_answer_text


class _Host:
    def __init__(self):
        self.tutor_daemon = _Tutor()
        self.chat_mode = False
        self._chat_processing = False
        self._chat_last_activity_at = 0.0


def test_external_need_gate_only_allows_fresh_local_verified_or_real_sensor():
    gate = ExternalNeedGate()

    stable = DiscoveryPlan(
        lane="fresh_curiosity",
        topic="Vì sao bạch tuộc có ba trái tim?",
        needs_external=True,
        confidence=0.9,
    )
    assert gate.allow(stable) == (False, "stable_knowledge_main_model_can_handle")

    local = replace(
        stable,
        lane="vietnam_local_signal",
        topic="Tin công nghệ mới trong nước hôm nay",
        freshness_required=True,
    )
    assert gate.allow(local)[0] is True

    room = replace(
        stable,
        lane="user_environment",
        topic="Nhiệt độ phòng user hiện tại",
    )
    assert gate.allow(room, room_sensor_available=False) == (False, "room_sensor_missing")
    assert gate.allow(room, room_sensor_available=True) == (True, "room_sensor")

    outdoor = replace(
        stable,
        lane="user_environment",
        topic="Thời tiết ngoài trời hiện tại tại nơi User ở",
        freshness_required=True,
    )
    assert gate.allow(outdoor, configured_location=False) == (False, "configured_location_missing")
    assert gate.allow(outdoor, configured_location=True) == (True, "outdoor_weather_requires_fresh_data")


def test_tutor_artifact_becomes_verified_discovery_and_can_be_shared(tmp_path):
    host = _Host()
    runtime = DiscoveryRuntime(host, _Router(), logger=_Logger(), state_path=tmp_path / "discovery.json")
    host.tutor_daemon._eris_discovery_meta = {
        "plan": DiscoveryPlan(
            lane="vietnam_local_signal",
            topic="Tin AI Việt Nam hôm nay",
            needs_external=True,
            freshness_required=True,
            verification_required=True,
            eris_interest=0.8,
            user_relevance=0.7,
            novelty=0.7,
            importance=0.7,
            confidence=0.8,
            reason="Tín hiệu địa phương đáng kể.",
        ).to_dict()
    }
    host.tutor_daemon.search_now("Tin AI Việt Nam hôm nay")

    record = runtime.sync_tutor_artifact()
    assert record is not None
    assert record.verified is True
    assert record.source == "tutor_gemini"
    assert "Nguồn A" in record.evidence

    ready = runtime.ready_records()
    assert ready and ready[0].discovery_id == record.discovery_id

    plan = IntentionPlan.from_mapping(
        {
            "speak": True,
            "motive": "grounded_curiosity",
            "strategy": "share_discovery",
            "topic": "Kể một thứ thú vị",
            "importance": 0.8,
            "confidence": 0.8,
        },
        channel="autonomous",
    )
    bound, grounding, discovery_id = runtime.bind_plan(plan)
    assert discovery_id == record.discovery_id
    assert "verified_summary" in grounding
    assert f"discovery:{record.discovery_id}" in bound.evidence_refs

    runtime.mark_spoken(discovery_id, "Tôi vừa đào được một chuyện khá hay.")
    assert runtime.ready_records() == ()
    stored = runtime.snapshot().records[-1]
    assert stored.shared is True
    assert stored.shared_text.startswith("Tôi vừa đào")



def test_direct_user_tutor_search_is_not_claimed_as_eris_discovery(tmp_path):
    host = _Host()
    runtime = DiscoveryRuntime(host, _Router(), logger=_Logger(), state_path=tmp_path / "discovery.json")

    # Không có marker do DiscoveryRuntime tạo: đây là search trực tiếp từ User.
    host.tutor_daemon.search_now("User vừa yêu cầu tra cứu một tin")
    assert runtime.sync_tutor_artifact() is None
    assert runtime.snapshot().records == ()

def test_environment_signal_never_aliases_gpu_or_weather_to_room_temperature(tmp_path):
    runtime = DiscoveryRuntime(_Host(), _Router(), state_path=tmp_path / "discovery.json")
    context = runtime.environment_signal(
        {
            "gpu_temperature_c": 72.0,
            "outdoor_temperature_c": 34.0,
            "active_app": "Godot",
        }
    )
    assert context["room_temperature"]["available"] is False
    assert context["gpu_temperature_c"] == 72.0

    context = runtime.environment_signal({"room_temperature_c": 28.5})
    assert context["room_temperature"] == {
        "available": True,
        "value_c": 28.5,
        "source": "runtime_sensor",
    }


def test_background_search_records_real_activity_and_artifact(tmp_path):
    host = _Host()
    runtime = DiscoveryRuntime(host, _Router(), logger=_Logger(), state_path=tmp_path / "discovery.json")
    plan = DiscoveryPlan(
        lane="vietnam_local_signal",
        topic="Một tin công nghệ Việt Nam mới trong 24 giờ",
        needs_external=True,
        freshness_required=True,
        verification_required=True,
        eris_interest=0.8,
        user_relevance=0.7,
        novelty=0.7,
        importance=0.7,
        confidence=0.85,
        reason="Tín hiệu địa phương đáng mang về khoe.",
    )
    runtime._start_search(plan, now=time.time())
    runtime._job_thread.join(timeout=2.0)

    state = runtime.snapshot()
    assert state.current_activity.status == "done"
    assert state.records
    assert state.records[-1].verified is True
    assert state.records[-1].lane == "vietnam_local_signal"
    assert getattr(host.tutor_daemon, "_eris_discovery_meta", {}) == {}


def test_yandere_is_a_derived_attractor_not_a_seeded_mode():
    base = IdentityProfile()
    assert base.derived_forms()["yandere_tendency"] < 0.30
    assert "yandere_tendency" not in base.prompt_summary().casefold()

    rel = RelationshipIdentity.from_mapping(
        {
            **base.primary_relationship().to_dict(),
            "attachment_intensity": 0.95,
            "possessiveness": 0.94,
            "jealousy": 0.91,
            "competition_sensitivity": 0.82,
            "resentment": 0.70,
        }
    )
    profile = IdentityProfile.from_mapping(
        {
            **base.to_dict(),
            "relationships": {"primary_user": rel.to_dict()},
            "motives": {
                **base.motives,
                "need_for_exclusivity": 0.90,
                "need_for_control": 0.72,
            },
            "values": {**base.values, "selective_loyalty": 0.88},
        }
    )
    assert profile.derived_forms()["yandere_tendency"] >= 0.80
    assert "yandere_tendency" in profile.panel_view()["active_forms"]
    assert "yandere" not in profile.prompt_summary().casefold()
