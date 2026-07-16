# -*- coding: utf-8 -*-
"""Các lane model phụ cho Social Cognition V2.

- Llama 3.1 8B: parser nhanh, chỉ refine top-k hypothesis khi lượt mơ hồ.
- Qwen3 32B: deliberator/critic cho repair, banter, từ chối, tức giận.
- Terra (client chính): chỉ rewrite câu cuối khi critic phát hiện lỗi nặng.

Tất cả method đều fail-open. Provider chết thì contract deterministic vẫn chạy;
không có chuyện API 429 kéo theo mất luôn khả năng đối nhân xử thế.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from runtime.social_cognition_v2 import SocialCritique, SocialHypothesis, TaskAppraisal


def _message_content(payload: Any) -> str:
    if not isinstance(payload, Mapping):
        return ""
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message", {}) if isinstance(choices[0], Mapping) else {}
        if isinstance(message, Mapping):
            content = message.get("content", "")
            if isinstance(content, str):
                return content.strip()
    candidates = payload.get("candidates")
    if isinstance(candidates, list) and candidates:
        content = candidates[0].get("content", {}) if isinstance(candidates[0], Mapping) else {}
        parts = content.get("parts", []) if isinstance(content, Mapping) else []
        if isinstance(parts, list):
            return "\n".join(str(part.get("text", "")) for part in parts if isinstance(part, Mapping)).strip()
    return ""


def _json_object(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if not raw:
        return {}
    try:
        value = json.loads(raw)
        return dict(value) if isinstance(value, Mapping) else {}
    except Exception:
        pass
    match = re.search(r"\{.*\}", raw, flags=re.S)
    if not match:
        return {}
    try:
        value = json.loads(match.group(0))
        return dict(value) if isinstance(value, Mapping) else {}
    except Exception:
        return {}


@dataclass(frozen=True, slots=True)
class ModelLaneResult:
    ok: bool
    payload: Mapping[str, Any]
    source: str
    error: str = ""


class SocialModelRouter:
    def __init__(self, llm_service: Any, *, logger: Any | None = None) -> None:
        self.llm_service = llm_service
        self.logger = logger

    def _call_json(
        self,
        client: Any,
        *,
        system: str,
        user: str,
        max_tokens: int,
        temperature: float = 0.1,
        reasoning_effort: str | None = None,
        source: str,
    ) -> ModelLaneResult:
        if client is None:
            return ModelLaneResult(False, {}, source, "client_unavailable")
        try:
            raw = client.create_chat_completion(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user + "\nReturn JSON only."},
                ],
                temperature=temperature,
                frequency_penalty=0.0,
                presence_penalty=0.0,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
                reasoning_effort=reasoning_effort,
            )
            payload = _json_object(_message_content(raw))
            return ModelLaneResult(bool(payload), payload, source, "" if payload else "empty_json")
        except Exception as exc:  # noqa: BLE001
            if self.logger is not None:
                try:
                    self.logger.debug("[social model] %s failed: %s", source, exc)
                except Exception:
                    pass
            return ModelLaneResult(False, {}, source, f"{type(exc).__name__}:{exc}")

    @property
    def parser_client(self) -> Any | None:
        return getattr(self.llm_service, "social_parser_client", None)

    @property
    def critic_client(self) -> Any | None:
        return getattr(self.llm_service, "social_critic_client", None)

    @property
    def main_client(self) -> Any | None:
        return getattr(self.llm_service, "client", None)

    def refine_hypotheses(
        self,
        *,
        user_text: str,
        history: Sequence[str],
        hypotheses: Sequence[SocialHypothesis],
        failed_claim: str,
        task: Mapping[str, Any],
        ambiguity: float,
    ) -> tuple[SocialHypothesis, ...]:
        if ambiguity < 0.38:
            return tuple(hypotheses)
        seed = [item.to_dict() for item in hypotheses]
        result = self._call_json(
            self.parser_client,
            system=(
                "Bạn là pragmatic parser tiếng Việt. Không viết câu trả lời. Giữ nhiều giả thuyết nếu mơ hồ. "
                "Phân biệt joke/banter, correction, task literal, insult thật, lệnh chán, yêu cầu thân mật. "
                "Không chẩn đoán cảm xúc hay động cơ user. Output: {hypotheses:[{intent,probability,target,evidence_spans,expected_response}]}."
            ),
            user=json.dumps({
                "user_text": user_text,
                "recent_history": list(history)[-6:],
                "seed_hypotheses": seed,
                "failed_claim": failed_claim,
                "task": dict(task),
            }, ensure_ascii=False),
            max_tokens=480,
            temperature=0.05,
            source="llama_social_parser",
        )
        if not result.ok:
            return tuple(hypotheses)
        raw_items = result.payload.get("hypotheses", [])
        if not isinstance(raw_items, list):
            return tuple(hypotheses)
        parsed: list[SocialHypothesis] = []
        for item in raw_items[:5]:
            if not isinstance(item, Mapping):
                continue
            try:
                probability = max(0.001, min(1.0, float(item.get("probability", 0.0) or 0.0)))
            except (TypeError, ValueError):
                continue
            intent = str(item.get("intent", "") or "").strip()
            if not intent:
                continue
            spans = item.get("evidence_spans", ())
            if isinstance(spans, str):
                spans = (spans,)
            elif isinstance(spans, list):
                spans = tuple(str(value) for value in spans if str(value).strip())
            else:
                spans = ()
            parsed.append(SocialHypothesis(
                intent=intent,
                probability=probability,
                target=str(item.get("target", "conversation") or "conversation"),
                evidence_spans=tuple(spans),
                expected_response=str(item.get("expected_response", "") or ""),
                source="llama_social_parser",
            ))
        if not parsed:
            return tuple(hypotheses)
        total = sum(item.probability for item in parsed) or 1.0
        return tuple(
            SocialHypothesis(
                item.intent,
                item.probability / total,
                item.target,
                item.evidence_spans,
                item.expected_response,
                item.source,
            )
            for item in sorted(parsed, key=lambda value: value.probability, reverse=True)[:4]
        )

    def deliberate(
        self,
        *,
        user_text: str,
        history: Sequence[str],
        hypotheses: Sequence[SocialHypothesis],
        failed_claim: str,
        social_state: Mapping[str, Any],
        task: Mapping[str, Any],
    ) -> dict[str, Any]:
        result = self._call_json(
            self.critic_client,
            system=(
                "Bạn là social deliberator của Eris, không phải người viết câu cuối. Chọn response move phù hợp. "
                "Eris quan sát, kín, hài khô, có quyền từ chối việc vô nghĩa, nhưng không overreact. "
                "Correction phải nêu claim sai cụ thể. Profanity trong joke không mặc định là insult. "
                "Giận phải tích lũy theo state, không nhảy mức. Output: {response_move,why,risk_flags,required_content}."
            ),
            user=json.dumps({
                "user_text": user_text,
                "history": list(history)[-6:],
                "hypotheses": [item.to_dict() for item in hypotheses],
                "failed_claim": failed_claim,
                "social_state": dict(social_state),
                "task": dict(task),
            }, ensure_ascii=False),
            max_tokens=560,
            temperature=0.10,
            reasoning_effort="default",
            source="qwen_social_deliberator",
        )
        return dict(result.payload) if result.ok else {}

    def critique(
        self,
        *,
        candidate_text: str,
        user_text: str,
        contract: Mapping[str, Any],
    ) -> SocialCritique:
        result = self._call_json(
            self.critic_client,
            system=(
                "Bạn là critic độc lập. Không viết lại câu. Kiểm tra candidate có trả đúng intent, đúng response move, "
                "repair cụ thể, không quá lạnh/ngoan/giận, không lộ jargon nội bộ. "
                "Output: {pass:boolean,severity:0..1,issues:[...],rewrite_instruction:string}."
            ),
            user=json.dumps({
                "user_text": user_text,
                "candidate": candidate_text,
                "contract": dict(contract),
            }, ensure_ascii=False),
            max_tokens=420,
            temperature=0.0,
            reasoning_effort="default",
            source="qwen_social_critic",
        )
        if not result.ok:
            return SocialCritique(source=result.source)
        issues = result.payload.get("issues", ())
        if isinstance(issues, str):
            issues = (issues,)
        elif isinstance(issues, list):
            issues = tuple(str(item) for item in issues if str(item).strip())
        else:
            issues = ()
        try:
            severity = max(0.0, min(1.0, float(result.payload.get("severity", 0.0) or 0.0)))
        except (TypeError, ValueError):
            severity = 0.0
        return SocialCritique(
            pass_check=bool(result.payload.get("pass", not issues)),
            severity=severity,
            issues=tuple(issues),
            rewrite_instruction=str(result.payload.get("rewrite_instruction", "") or ""),
            source=result.source,
        )

    def rewrite_with_main(
        self,
        *,
        candidate_text: str,
        user_text: str,
        contract: Mapping[str, Any],
        instruction: str,
    ) -> dict[str, str]:
        result = self._call_json(
            self.main_client,
            system=(
                "Bạn là Eris. Chỉ sửa một câu public theo social contract. Giữ cá tính kín, sắc, hài khô; "
                "không support-bot, không jargon nội bộ, không claim động cơ user. "
                "Output JSON: {text,delivery_hint,nonverbal_cue,stage_motion}."
            ),
            user=json.dumps({
                "user_text": user_text,
                "candidate": candidate_text,
                "social_contract": dict(contract),
                "rewrite_instruction": instruction,
            }, ensure_ascii=False),
            max_tokens=380,
            temperature=0.35,
            source="terra_social_rewrite",
        )
        if not result.ok:
            return {}
        return {
            key: str(result.payload.get(key, "") or "").strip()
            for key in ("text", "delivery_hint", "nonverbal_cue", "stage_motion")
        }


__all__ = ["ModelLaneResult", "SocialModelRouter"]
