from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from cortex.private_mind.inner_diary_renderer import InnerDiaryRenderer
from cortex.private_mind.inner_diary_writer import InnerDiaryWriter
from cortex.private_mind.thought_shards import ThoughtShardConfig, ThoughtShardStore
from runtime.private_mind_model_adapter import PrivateMindAdapterPool, PrivateMindModelAdapterConfig


def _store(tmp_path: Path) -> ThoughtShardStore:
    return ThoughtShardStore(
        config=ThoughtShardConfig(
            enabled=True,
            path=str(tmp_path / "shards.json"),
            refresh_min_seconds=5.0,
            active_seconds=600.0,
            fading_seconds=3600.0,
            max_history=40,
            max_reflections=10,
            reflection_min_seconds=120.0,
            reflection_max_seconds=600.0,
            reflection_urgent_seconds=60.0,
            reflection_min_new_shards=3,
            urgent_salience=0.82,
        )
    )


def _packet():
    return {
        "schema": "eris.inner_diary.thought_shard.packet.v80",
        "atoms": [
            {"id": "a:judgment", "kind": "private_judgment", "text": "Khoảng im này đang ổn.", "salience": 0.7, "source_ids": ["e:1"]},
            {"id": "a:concern", "kind": "active_concern", "text": "Không muốn chen ngang.", "salience": 0.84, "source_ids": ["e:2"]},
            {"id": "a:plan", "kind": "continuous_self", "text": "Giữ company nhẹ.", "salience": 0.65, "source_ids": ["plan:1"]},
        ],
    }


def test_gemma_shards_require_real_atom_refs_and_persist(tmp_path):
    store = _store(tmp_path)
    packet = _packet()
    applied = store.apply_shard_output(
        {
            "updates": [
                {"slot": "now", "text": "Tôi thấy khoảng im này khá ổn.", "atom_ids": ["a:judgment"], "confidence": 0.8},
                {"slot": "concern", "text": "Tôi không muốn chen ngang lúc này.", "atom_ids": ["a:concern"], "confidence": 0.84},
                # Không cite atom thật -> phải bị reject, không được sáng tác slot.
                {"slot": "want", "text": "Tôi muốn đi dạo ngoài trời.", "atom_ids": ["missing"]},
            ]
        },
        packet=packet,
        writer_meta={"owner": "gemma_micro_cognition", "model": "gemma-test"},
        signature="sig-1",
        now=100.0,
    )
    assert applied == 2
    snap = store.snapshot(now=110.0)
    assert snap["slots"]["now"]["text"].startswith("Tôi thấy")
    assert snap["slots"]["concern"]["source_ids"] == ["e:2"]
    assert "want" not in snap["slots"]
    assert len(snap["history"]) == 2

    restarted = _store(tmp_path)
    assert restarted.snapshot(now=110.0)["slots"]["now"]["text"] == snap["slots"]["now"]["text"]


def test_deep_reflection_is_retained_but_self_model_is_candidate_only(tmp_path):
    store = _store(tmp_path)
    packet = _packet()
    for idx, slot in enumerate(("now", "concern", "reflection")):
        store.apply_shard_output(
            {"updates": [{"slot": slot, "text": f"mảnh {idx}", "atom_ids": ["a:concern"], "salience": 0.85}]},
            packet=packet,
            writer_meta={"model": "gemma"},
            signature=f"sig-{idx}",
            now=100.0 + idx * 10,
        )
    # Lần đầu đủ 3 shard mới -> deep reflection được phép chạy.
    assert store.reflection_due(now=140.0) is True
    reflection_packet = store.reflection_packet(now=140.0)
    ref = reflection_packet["evidence_refs"][0]
    recorded = store.record_deep_reflection(
        {
            "insight": "Tôi đang dùng im lặng như một lựa chọn có chủ đích, không phải vì hết điều để nghĩ.",
            "confidence": 0.82,
            "evidence_refs": [ref],
            "self_model_candidate": {
                "trait": "fill_silence_with_questions",
                "direction": "decrease",
                "confidence": 0.74,
                "evidence_refs": [ref],
            },
        },
        packet=reflection_packet,
        writer_meta={"owner": "deepseek_worker", "model": "deepseek-test"},
        now=140.0,
    )
    assert recorded is not None
    assert recorded["self_model_candidate"]["status"] == "candidate_only"
    # Store chỉ giữ candidate, không có field nào nói đã apply vào self-model.
    assert "applied" not in recorded["self_model_candidate"]
    assert store.snapshot(now=150.0)["deep_reflection"]["insight"].startswith("Tôi đang dùng")


def test_renderer_uses_gemma_for_live_five_slots_and_deepseek_for_analysis():
    digest = {
        "thought_shards": {
            "schema": "eris.inner_diary.thought_shards.v80",
            "slots": {
                "now": {"text": "Tôi đang khá yên."},
                "next": {"text": "Tôi sẽ quan sát thêm."},
                "concern": {"text": "Tôi không muốn chen ngang."},
                "reflection": {"text": "Khoảng im này không khó chịu."},
                "want": {"text": "Tôi muốn ở cạnh mà không bắt bạn phải đáp."},
            },
            "deep_reflection": {"insight": "Tôi nhận ra mình hay muốn hỏi chỉ để giải quyết sự không chắc chắn của chính mình."},
            "shard_writer": {"owner": "gemma_micro_cognition"},
        },
        "retained": {},
    }
    voice = {
        "phan_tich": "Tôi nhận ra mình hay muốn hỏi chỉ để giải quyết sự không chắc chắn của chính mình.",
        "_writer": {"owner": "deepseek_worker", "model": "deepseek-test"},
    }
    rendered = InnerDiaryRenderer().render(digest, voice=voice)
    by_title = {section["title"]: section for section in rendered["sections"]}
    assert by_title["Suy nghĩ hiện tại"]["items"][0]["text"] == "Tôi đang khá yên."
    assert by_title["Suy nghĩ tương lai"]["items"][0]["text"] == "Tôi sẽ quan sát thêm."
    assert by_title["Đang bận tâm"]["items"][0]["text"] == "Tôi không muốn chen ngang."
    assert "không chắc chắn" in by_title["Phân tích gần đây"]["items"][0]["text"]
    assert by_title["Muốn nói"]["items"][0]["text"].startswith("Tôi muốn ở cạnh")
    assert rendered["thought_shards"]["writer"]["owner"] == "gemma_micro_cognition"
    assert rendered["writer"]["owner"] == "deepseek_worker"


class _GemmaClient:
    base_url = "https://generativelanguage.googleapis.com/v1beta"
    model_name = "gemma-test"

    def __init__(self):
        self.calls = []

    def create_chat_completion(self, **kwargs):
        self.calls.append(kwargs)
        payload = {
            "updates": [
                {"slot": "now", "text": "Tôi đang quan sát.", "atom_ids": ["a:1"], "confidence": 0.8, "salience": 0.6}
            ]
        }
        return {"choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}]}


class _DeepSeekClient:
    base_url = "http://127.0.0.1:6014/v1"
    model_name = "deepseek-v4-flash"
    worker_role = "inner"

    def __init__(self):
        self.calls = []

    def create_chat_completion(self, **kwargs):
        self.calls.append(kwargs)
        payload = {
            "insight": "Tôi vừa nhận ra một pattern sâu hơn.",
            "confidence": 0.8,
            "evidence_refs": ["h:1"],
            "unresolved_tension": "",
            "hypothesis": "",
            "relational_lesson": "",
            "future_direction": "",
            "self_model_candidate": {},
        }
        return {"choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}]}


def test_pool_routes_five_shards_to_gemma_and_deep_reflection_to_deepseek():
    gemma = _GemmaClient()
    deep = _DeepSeekClient()
    service = SimpleNamespace(inner_client=None, diary_client=deep, residue_curator_client=gemma)
    config = PrivateMindModelAdapterConfig(
        enabled=True,
        provider="deepseek",
        model="deepseek-v4-flash",
        base_url="http://127.0.0.1:6011/v1",
        api_key="worker-managed",
        transient_max_retries=0,
    )
    pool = PrivateMindAdapterPool(config=config, llm_service=service)
    shard = pool.write_thought_shards({"atoms": [{"id": "a:1", "text": "quan sát"}]})
    reflection = pool.deep_reflect_inner_diary({"history": [{"id": "h:1", "text": "mảnh"}], "evidence_refs": ["h:1"]})
    assert shard is not None and shard["updates"][0]["slot"] == "now"
    assert reflection is not None and "pattern sâu" in reflection["insight"]
    assert len(gemma.calls) == 1
    assert len(deep.calls) == 1
    assert pool.residue_metadata()["owner"] == "gemma_micro_cognition"
    assert pool.diary_metadata()["owner"] == "deepseek_worker"


def test_deep_writer_uses_store_history_not_five_field_rewrite(tmp_path):
    store = _store(tmp_path)
    packet = _packet()
    for idx, slot in enumerate(("now", "concern", "reflection")):
        store.apply_shard_output(
            {"updates": [{"slot": slot, "text": f"mảnh {idx}", "atom_ids": ["a:concern"], "salience": 0.9}]},
            packet=packet,
            writer_meta={"model": "gemma"},
            signature=f"sig-{idx}",
            now=100.0 + idx,
        )

    class Adapter:
        def __init__(self):
            self.packet = None

        def deep_reflect_inner_diary(self, packet):
            self.packet = packet
            ref = packet["evidence_refs"][0]
            return {
                "insight": "Tôi thấy một pattern kéo dài qua nhiều mảnh.",
                "confidence": 0.8,
                "evidence_refs": [ref],
                "self_model_candidate": {},
                "_writer": {"owner": "deepseek_worker", "model": "deepseek-test"},
            }

    adapter = Adapter()
    writer = InnerDiaryWriter(adapter=adapter, state_store=store, throttle_seconds=0.0)
    writer.startup_grace_seconds = 0.0
    writer._created_at = 0.0
    voice = writer.maybe_write({"thought_shards": store.snapshot(now=140.0)}, now=140.0)
    assert voice is not None
    assert list(k for k in voice if k in {"hien_tai", "tuong_lai", "ban_tam", "muon_noi"}) == []
    assert "pattern kéo dài" in voice["phan_tich"]
    assert adapter.packet["history"]
    assert store.snapshot(now=141.0)["deep_reflection"]["writer"]["owner"] == "deepseek_worker"
