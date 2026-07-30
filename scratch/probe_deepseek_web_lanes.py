from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import time
from collections.abc import Mapping
from typing import Any


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.environ["ERIS_PROJECT_ROOT"] = REPO_ROOT
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from cortex.private_mind.contracts import EvidenceDossier, ThoughtFragment
from domain.decision import Decision
from eris_secrets import apply_secrets_to_environ, load_env_file
from llm.deepseek_workers import canonical_json_line, load_worker_spec
from llm.process_manager import RemoteModelProcessManager
from llm.service import LlmService
from runtime.ai_orchestrated.model_router import (
    AIRuntimeModelRouter,
    OBJECTIVE_OBSERVATION_SCHEMA,
    _json,
)
from runtime.private_mind_model_adapter import RuntimePrivateMindModelAdapter
from runtime.semantic_frame import validate_assistant_act, validate_semantic_frame
from runtime.utterance_spec import UtteranceSpec


ROLES = ("companion", "observer", "critic", "inner", "style")


def _content(payload: Any) -> str:
    if not isinstance(payload, Mapping):
        return ""
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0] if isinstance(choices[0], Mapping) else {}
    message = first.get("message") if isinstance(first, Mapping) else {}
    return str(message.get("content", "") or "") if isinstance(message, Mapping) else ""


def _reasoning(payload: Any) -> str:
    if not isinstance(payload, Mapping):
        return ""
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0] if isinstance(choices[0], Mapping) else {}
    message = first.get("message") if isinstance(first, Mapping) else {}
    if not isinstance(message, Mapping):
        return ""
    return str(message.get("reasoning_content") or message.get("reasoning") or "")


def _preview(value: Any, limit: int = 280) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def _json_keys(text: str) -> list[str]:
    try:
        value = json.loads(canonical_json_line(text))
    except Exception:
        value = _json(text, public_reply=False)
    return sorted(str(key) for key in value.keys()) if isinstance(value, Mapping) else []


class CaptureRawClient:
    def __init__(self, target: Any) -> None:
        self.target = target
        self.calls: list[dict[str, Any]] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self.target, name)

    def create_chat_completion(self, **kwargs: Any) -> Any:
        started = time.perf_counter()
        try:
            result = self.target.create_chat_completion(**kwargs)
        except Exception as exc:
            self.calls.append({
                "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 1),
                "error": f"{type(exc).__name__}:{exc}",
            })
            raise
        self.calls.append({
            "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 1),
            "result": result,
        })
        return result


class CaptureWorker:
    def __init__(self, target: Any) -> None:
        self.target = target
        self.calls: list[dict[str, Any]] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self.target, name)

    def create_chat_completion(self, **kwargs: Any) -> Any:
        started = time.perf_counter()
        try:
            result = self.target.create_chat_completion(**kwargs)
        except Exception as exc:
            self.calls.append({
                "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 1),
                "error": f"{type(exc).__name__}:{exc}",
            })
            raise
        self.calls.append({
            "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 1),
            "result": result,
        })
        return result


def _capture_worker(worker: Any) -> tuple[CaptureWorker, CaptureRawClient]:
    raw = CaptureRawClient(worker._client)
    worker._client = raw
    return CaptureWorker(worker), raw


def _last_result(calls: list[dict[str, Any]]) -> dict[str, Any]:
    return next((call for call in reversed(calls) if "result" in call), {})


def _call_summary(worker: CaptureWorker, raw: CaptureRawClient) -> dict[str, Any]:
    raw_result = _last_result(raw.calls)
    wrapped_result = _last_result(worker.calls)
    raw_payload = raw_result.get("result", {})
    wrapped_payload = wrapped_result.get("result", {})
    raw_text = _content(raw_payload)
    wrapped_text = _content(wrapped_payload)
    return {
        "raw_calls": len(raw.calls),
        "wrapped_calls": len(worker.calls),
        "raw_elapsed_ms": raw_result.get("elapsed_ms", 0.0),
        "wrapped_elapsed_ms": wrapped_result.get("elapsed_ms", 0.0),
        "raw_content_chars": len(raw_text),
        "wrapped_content_chars": len(wrapped_text),
        "reasoning_chars": len(_reasoning(raw_payload)),
        "raw_json_keys": _json_keys(raw_text),
        "wrapped_json_keys": _json_keys(wrapped_text),
        "raw_preview": _preview(raw_text),
        "wrapped_preview": _preview(wrapped_text),
        "wrapper_changed_content": raw_text.strip() != wrapped_text.strip(),
        "raw_errors": [call["error"] for call in raw.calls if call.get("error")],
        "worker_errors": [call["error"] for call in worker.calls if call.get("error")],
    }


def main() -> None:
    load_env_file(force=True)
    apply_secrets_to_environ()

    logger = logging.getLogger("deepseek-lane-probe")
    logger.addHandler(logging.NullHandler())
    logger.setLevel(logging.CRITICAL)

    specs = {role: load_worker_spec(role) for role in ROLES}
    fingerprints: dict[str, str] = {}
    for spec in specs.values():
        digest = hashlib.sha256(spec.api_key.encode("utf-8")).hexdigest() if spec.api_key else ""
        if digest and digest not in fingerprints:
            fingerprints[digest] = f"key_{len(fingerprints) + 1}"

    report: dict[str, Any] = {
        "config": {
            role: {
                "configured": spec.configured,
                "key_slot": fingerprints.get(
                    hashlib.sha256(spec.api_key.encode("utf-8")).hexdigest() if spec.api_key else "",
                    "missing",
                ),
                "base_url": spec.base_url,
                "model": spec.model,
                "jsonl_enabled": spec.jsonl_enabled,
                "jsonl_repair_attempts": spec.jsonl_repair_attempts,
            }
            for role, spec in specs.items()
        },
        "lanes": {},
    }

    manager = RemoteModelProcessManager(logger=logger, project_root=REPO_ROOT)
    captures: dict[str, tuple[CaptureWorker, CaptureRawClient]] = {}
    for role in ROLES:
        worker = manager.build_deepseek_worker_client(role, required=True)
        captures[role] = _capture_worker(worker)

    companion, companion_raw = captures["companion"]
    observer, observer_raw = captures["observer"]
    critic, critic_raw = captures["critic"]
    inner, inner_raw = captures["inner"]
    style, style_raw = captures["style"]

    service = LlmService(
        companion,
        style_client=style,
        observer_client=observer,
        critic_client=critic,
        inner_client=inner,
        social_parser_client=observer,
        social_critic_client=critic,
        logger=logger,
    )
    router = AIRuntimeModelRouter(service, logger=logger)

    try:
        payload = router.generate_public_reply(
            chat_history=[],
            user_text="chơi cờ vua với tui hơm",
            memory_context="",
            grounding_context="primary_source=user_text; allowed_sources=user_text",
            relationship_context="casual, familiar",
            personality_context="warm, restrained, dry humor",
            engagement_context="chess waiting_for_board; do not claim board visibility",
            routing_context="clear_simple_turn",
            discourse_context="current direct invitation",
            allow_fallback=False,
            language_hint="vi",
            speech_language_hint="ja",
        )
        call = _call_summary(companion, companion_raw)
        raw_parsed = _json(_content(companion_raw.calls[-1]["result"]))
        semantic_validation = validate_semantic_frame(raw_parsed.get("semantic_frame", {}))
        act_validation = validate_assistant_act(raw_parsed.get("assistant_act", {}))
        raw_utterance = UtteranceSpec.from_mapping(raw_parsed)
        call.update({
            "downstream_text": str(payload.get("text", "") or ""),
            "downstream_speech_text": str(payload.get("speech_text", "") or ""),
            "downstream_should_speak": bool(payload.get("should_speak", False)),
            "raw_display_text": raw_utterance.display.text,
            "raw_speech_text": raw_utterance.speech.text,
            "semantic_violations": list(semantic_validation.violations),
            "assistant_act_violations": list(act_validation.violations),
            "text_dropped": bool(raw_utterance.display.text and not str(payload.get("text", "") or "").strip()),
        })
        report["lanes"]["chat_companion"] = call
    except Exception as exc:
        report["lanes"]["chat_companion"] = {"error": f"{type(exc).__name__}:{exc}"}

    try:
        observation = router.observe_completed_turn(
            turn_id="probe-observer-1",
            turn_seq=1,
            user_text="Tôi rủ cậu chơi cờ, đừng biến nó thành bài phân tích.",
            assistant_text="Ừ, chơi chứ. Mở bàn cờ đi.",
            recent_history=[],
            state_summary={"semantic_frame": {"user_act": "direct_request", "target": "assistant"}},
            timeout_seconds=45.0,
        )
        call = _call_summary(observer, observer_raw)
        call["raw_content_full"] = [_content(item.get("result", {})) for item in observer_raw.calls]
        call["wrapped_content_full"] = [_content(item.get("result", {})) for item in observer.calls]
        final = observation.to_dict()
        raw_keys = set(call.get("raw_json_keys", []))
        call.update({
            "typed_source": final.get("source", ""),
            "typed_confidence": final.get("confidence", 0.0),
            "typed_user_act": final.get("user_act", {}),
            "typed_keys": sorted(final.keys()),
            "raw_keys_absent_after_mapping": sorted(raw_keys - set(final.keys())),
        })
        report["lanes"]["observer"] = call
    except Exception as exc:
        report["lanes"]["observer"] = {"error": f"{type(exc).__name__}:{exc}"}

    try:
        critic_payload = router._call(
            critic,
            system=router._observer_prompt(deep=True),
            payload={
                "turn_id": "probe-critic-1",
                "turn_seq": 1,
                "event_kind": "chat",
                "user_text": "Câu trả lời đúng ý nhưng runtime lại thay bằng fallback.",
                "assistant_text": "Tôi hụt nhịp ở lượt này.",
                "semantic_frame": {"user_act": "correction", "target": "assistant"},
            },
            schema=OBJECTIVE_OBSERVATION_SCHEMA,
            name="eris_cognitive_observation_deep_probe",
            max_tokens=820,
            timeout_seconds=60.0,
        )
        call = _call_summary(critic, critic_raw)
        call["raw_content_full"] = [_content(item.get("result", {})) for item in critic_raw.calls]
        call["wrapped_content_full"] = [_content(item.get("result", {})) for item in critic.calls]
        call.update({
            "parsed_keys": sorted(critic_payload.keys()),
            "parser_empty": not bool(critic_payload),
            "raw_keys_absent_after_parser": sorted(set(call.get("raw_json_keys", [])) - set(critic_payload.keys())),
        })
        report["lanes"]["critic"] = call
    except Exception as exc:
        report["lanes"]["critic"] = {"error": f"{type(exc).__name__}:{exc}"}

    try:
        adapter = RuntimePrivateMindModelAdapter.from_env(llm_service=service, logger=logger)
        if adapter is None:
            raise RuntimeError("private_mind_adapter_unavailable")
        dossier = EvidenceDossier(
            dossier_id="probe-private-mind-1",
            recent_user_turns=({
                "evidence_id": "turn.user.1",
                "text": "Tôi muốn biết vì sao câu đúng lại bị fallback đè.",
                "intent": "debug_runtime_drop",
            },),
            active_goal="Tìm đúng điểm runtime làm rơi output.",
            current_task="Kiểm tra DeepSeek Web lanes.",
            evidence_index={"turn.user.1": {"kind": "user_text"}},
            metadata={"recent_thoughts": ["Câu model có thể đúng nhưng envelope bị tách."]},
        )
        fragment_payload = adapter.evaluate_fragment("intent_evaluator", dossier)
        fragment = ThoughtFragment.from_mapping(fragment_payload or {})
        judgment_payload = adapter.synthesize_judgment(dossier, (fragment,))
        call = _call_summary(inner, inner_raw)
        call.update({
            "inner_total_raw_calls": len(inner_raw.calls),
            "inner_total_wrapped_calls": len(inner.calls),
            "fragment_keys": sorted((fragment_payload or {}).keys()),
            "fragment_claim": str((fragment_payload or {}).get("claim", "") or ""),
            "judgment_keys": sorted((judgment_payload or {}).keys()),
            "judgment_text": str((judgment_payload or {}).get("dominant_judgment", "") or ""),
            "fragment_empty": not bool(fragment_payload),
            "judgment_empty": not bool(judgment_payload),
            "adapter_status": adapter.debug_status(),
        })
        report["lanes"]["private_mind_inner"] = call
    except Exception as exc:
        report["lanes"]["private_mind_inner"] = {"error": f"{type(exc).__name__}:{exc}"}

    try:
        original = "Tôi chưa thấy bàn cờ nên chưa thể đi nước."
        decision = Decision(text=original, animation="stand")
        rewritten = service.rewrite_text_with_local_style(decision, channel="deepseek_lane_probe")
        call = _call_summary(style, style_raw)
        call.update({
            "original_text": original,
            "final_text": rewritten.text,
            "accepted_rewrite": rewritten.text != original,
            "debug_trace": rewritten.debug_trace,
            "text_dropped": not bool(str(rewritten.text or "").strip()),
        })
        report["lanes"]["style"] = call
    except Exception as exc:
        report["lanes"]["style"] = {"error": f"{type(exc).__name__}:{exc}"}

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
