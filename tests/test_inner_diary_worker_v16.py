from __future__ import annotations

import json
import logging
from types import SimpleNamespace

from cortex.private_mind.inner_diary_renderer import InnerDiaryRenderer
from cortex.private_mind.inner_diary_writer import InnerDiaryWriter
from llm.process_manager import RemoteModelProcessManager
from llm.service import LlmService
from runtime.private_mind_model_adapter import (
    PrivateMindAdapterPool,
    PrivateMindModelAdapterConfig,
)


class _FakeDiaryClient:
    base_url = "http://127.0.0.1:6011/v1"
    model_name = "deepseek-v4-flash"
    worker_role = "inner"

    def __init__(self, payload: dict[str, object] | None = None):
        self.payload = payload or {
            "hien_tai": "Tôi đang lặng lẽ nối lại những điều còn dang dở.",
            "tuong_lai": "Tôi muốn nhìn thêm một bước trước khi lên tiếng.",
            "ban_tam": "Có một điều chưa thật sự yên trong tôi.",
            "phan_tich": "Tôi vừa nhận ra mình đang thận trọng hơn bình thường.",
            "muon_noi": "Tôi vẫn ở đây.",
            "memory_echo": "Một lần bạn từng kiên nhẫn chờ tôi trả lời.",
        }
        self.calls: list[dict[str, object]] = []

    def create_chat_completion(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "choices": [
                {"message": {"content": json.dumps(self.payload, ensure_ascii=False)}}
            ]
        }


class _ExplodingClient:
    def __init__(self):
        self.calls = 0

    def create_chat_completion(self, **kwargs):
        self.calls += 1
        raise AssertionError("non-diary lane must not be called")


def test_inner_diary_defers_remote_writing_during_startup():
    class Adapter:
        def __init__(self):
            self.calls = 0

        def write_inner_diary(self, _facts):
            self.calls += 1
            return {"hien_tai": "ready"}

    adapter = Adapter()
    writer = InnerDiaryWriter(adapter=adapter, throttle_seconds=0.0)
    writer._created_at = 100.0
    writer.startup_grace_seconds = 60.0

    assert writer.maybe_write({"current": {"dominant_judgment": "boot thought"}}, now=120.0) is None
    assert adapter.calls == 0

    assert writer.maybe_write({"current": {"dominant_judgment": "boot thought"}}, now=161.0) == {"hien_tai": "ready", "tuong_lai": "", "ban_tam": "", "phan_tich": "", "muon_noi": "", "memory_echo": ""}
    assert adapter.calls == 1


def _config() -> PrivateMindModelAdapterConfig:
    return PrivateMindModelAdapterConfig(
        enabled=True,
        provider="deepseek",
        model="deepseek-v4-flash",
        base_url="http://127.0.0.1:6011/v1",
        api_key="worker-managed",
        transient_max_retries=0,
    )


def test_llm_service_keeps_a_distinct_diary_owner():
    companion = object()
    inner = object()
    diary = object()

    service = LlmService(companion, inner_client=inner, diary_client=diary)

    assert service.inner_client is inner
    assert service.diary_client is diary
    assert service.diary_client is not service.inner_client


def test_default_diary_owner_reuses_the_existing_inner_worker(monkeypatch, tmp_path):
    monkeypatch.setenv("ERIS_DS_BASE_URL", "http://127.0.0.1:6011/v1")
    monkeypatch.setenv("ERIS_DS_MODEL", "deepseek-v4-flash")
    monkeypatch.setenv("ERIS_DS_INNER_API_KEY", "inner-gateway-key")
    monkeypatch.delenv("ERIS_INNER_DIARY_WORKER_ROLE", raising=False)
    manager = RemoteModelProcessManager(
        logger=logging.getLogger("test.inner-diary.same-worker"),
        project_root=str(tmp_path),
    )

    inner = manager.build_inner_client()
    diary = manager.build_diary_client()

    assert diary is inner
    assert diary.worker_role == "inner"


def test_process_manager_selects_one_existing_worker_role(monkeypatch, tmp_path):
    manager = RemoteModelProcessManager(
        logger=logging.getLogger("test.inner-diary"),
        project_root=str(tmp_path),
    )
    selected: list[str] = []
    expected = object()

    def _build(role: str):
        selected.append(role)
        return expected

    monkeypatch.setenv("ERIS_INNER_DIARY_WORKER_ROLE", "critic")
    monkeypatch.setattr(manager, "build_deepseek_worker_client", _build)

    assert manager.build_diary_client() is expected
    assert selected == ["critic"]


def test_invalid_diary_role_falls_back_to_inner(monkeypatch, tmp_path):
    manager = RemoteModelProcessManager(
        logger=logging.getLogger("test.inner-diary.invalid"),
        project_root=str(tmp_path),
    )
    selected: list[str] = []

    monkeypatch.setenv("ERIS_INNER_DIARY_WORKER_ROLE", "imaginary_worker")
    monkeypatch.setattr(manager, "build_deepseek_worker_client", lambda role: selected.append(role) or object())

    manager.build_diary_client()

    assert selected == ["inner"]


def test_diary_write_uses_only_dedicated_client():
    diary = _FakeDiaryClient()
    inner = _ExplodingClient()
    service = SimpleNamespace(diary_client=diary, inner_client=inner)
    pool = PrivateMindAdapterPool(config=_config(), llm_service=service)

    result = pool.write_inner_diary(
        {
            "hien_tai": "Tôi đang nghĩ.",
            "memory_echoes": [
                {
                    "text": "Bạn từng kiên nhẫn chờ tôi.",
                    "evidence_id": "mem-7",
                    "source": "living_memory",
                }
            ],
        }
    )

    assert result is not None
    assert len(diary.calls) == 1
    assert inner.calls == 0
    assert result["_writer"] == {
        "owner": "deepseek_worker",
        "role": "inner",
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
        "configured": True,
    }


def test_missing_diary_client_does_not_borrow_inner_lane():
    inner = _ExplodingClient()
    service = SimpleNamespace(diary_client=None, inner_client=inner)
    pool = PrivateMindAdapterPool(config=_config(), llm_service=service)

    result = pool.write_inner_diary({"hien_tai": "Một ý nghĩ ngắn."})

    assert result is None
    assert inner.calls == 0


def test_renderer_memory_echo_keeps_real_provenance_and_writer():
    renderer = InnerDiaryRenderer()
    digest = {
        "menu": {
            "current_thought": {"dominant_judgment": "Tôi đang suy nghĩ."},
            "evidence_dossier": {
                "memory_hits": [
                    {
                        "text": "Bạn từng chọn ở lại khi cuộc trò chuyện khó khăn.",
                        "evidence_id": "memory-42",
                        "source": "living_user_memory",
                    }
                ]
            },
        }
    }
    voice = {
        "hien_tai": "Tôi đang nghĩ về điều ấy.",
        "memory_echo": "Tôi nhớ lần bạn đã chọn ở lại.",
        "_writer": {
            "owner": "deepseek_worker",
            "role": "inner",
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "configured": True,
        },
    }

    rendered = renderer.render(digest, voice)

    assert rendered["memory_echo"] == {
        "text": "Tôi nhớ lần bạn đã chọn ở lại.",
        "evidence_id": "memory-42",
        "source": "living_user_memory",
        "authored": True,
    }
    assert rendered["writer"]["role"] == "inner"
