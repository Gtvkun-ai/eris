from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Callable, Optional
import unicodedata

try:
    from ..domain import Decision
    from ..memory.memory_models import MemoryKind
    from ..memory.memory_query_compiler import MemoryQueryCompiler
    from ..memory.memory_query_executor import MemoryQueryExecutor
    from ..memory.memory_query_ir import QueryIntent, RecallAnswer, RelationRef
    from ..memory.memory_query_llm_parser import MemoryQueryLLMClient, MemoryQueryLLMParser
    from ..memory.memory_recall_policy import MemoryRecallSurfacePolicy
    from ..memory.memory_turn_annotator import TurnAnnotator
    from ..memory.memory_turn_graph import TurnGraph
    from .session_turn_ledger import SessionTurnLedger
except ImportError:
    from domain import Decision
    from memory.memory_models import MemoryKind
    from memory.memory_query_compiler import MemoryQueryCompiler
    from memory.memory_query_executor import MemoryQueryExecutor
    from memory.memory_query_ir import QueryIntent, RecallAnswer, RelationRef
    from memory.memory_query_llm_parser import MemoryQueryLLMClient, MemoryQueryLLMParser
    from memory.memory_recall_policy import MemoryRecallSurfacePolicy
    from memory.memory_turn_annotator import TurnAnnotator
    from memory.memory_turn_graph import TurnGraph
    from runtime.session_turn_ledger import SessionTurnLedger


SemanticLookupFn = Callable[[MemoryKind], Optional[Any]]
EpisodicLookupFn = Callable[[str], Optional[Any]]

_FACT_KEY_TO_MEMORY_KIND: dict[str, MemoryKind] = {
    "user.name": MemoryKind.USER_NAME,
    "user.birth_month": MemoryKind.USER_BIRTH_MONTH,
    "user.response_style": MemoryKind.USER_RESPONSE_STYLE,
}


@dataclass(slots=True)
class MemoryRecallAdapter:
    """
    Runtime adapter for structured memory recall.

    The public contract is intentionally simple: return a ready-to-send Decision
    before chat falls through to the general LLM answer path.
    """

    ledger: SessionTurnLedger
    memory_core: Any = None
    llm_service: Any = None
    semantic_lookup: SemanticLookupFn | None = None
    episodic_lookup: EpisodicLookupFn | None = None
    compiler: MemoryQueryCompiler | None = None
    executor: MemoryQueryExecutor | None = None
    surface_policy: MemoryRecallSurfacePolicy | None = None
    annotator: TurnAnnotator | None = None

    def try_answer(self, user_text: str) -> Optional[Decision]:
        outcome = self._recall(user_text)
        if outcome is None:
            return None
        return outcome.decision

    def try_answer_as_decision_payload(self, user_text: str) -> Optional[dict[str, Any]]:
        outcome = self._recall(user_text)
        if outcome is None:
            return None

        payload = outcome.decision.to_payload()
        payload["memory_source"] = outcome.answer.source.value
        payload["memory_surface"] = outcome.answer.surface.value
        return payload

    def _recall(self, user_text: str) -> Optional["_RecallOutcome"]:
        compiler = self._ensure_compiler()
        executor = self.executor or MemoryQueryExecutor()
        surface_policy = self.surface_policy or MemoryRecallSurfacePolicy()
        annotator = self.annotator or TurnAnnotator()

        compile_result = compiler.compile(user_text)
        if not compile_result.has_query or compile_result.best is None:
            return None
        if not self._is_recall_request(user_text, compile_result):
            return None
        if not self._should_intercept(compile_result.best):
            return None

        turn_graph = TurnGraph.from_session_ledger(
            self.ledger,
            annotator=annotator,
        )
        raw = executor.execute(
            compile_result.best,
            turn_graph=turn_graph,
            memory_core=self._execution_memory_core(),
        )
        answer = surface_policy.surface(raw)
        decision = self._build_decision(answer, compile_result=compile_result)
        return _RecallOutcome(decision=decision, answer=answer)

    def _should_intercept(self, best: Any) -> bool:
        confidence = float(getattr(best, "confidence", 0.0) or 0.0)
        ambiguity = float(getattr(best, "ambiguity", 1.0) or 1.0)
        if confidence < 0.60:
            return False
        if ambiguity > 0.78:
            return False
        return True

    def _is_recall_request(self, user_text: str, compile_result: Any) -> bool:
        best = getattr(compile_result, "best", None)
        hypotheses = tuple(getattr(compile_result, "hypotheses", ()) or ())
        if best is None or not hypotheses:
            return False
        top = hypotheses[0]
        if top.source == "semantic_hint":
            return False

        debug = getattr(compile_result, "debug", None)
        debug_notes = set(getattr(debug, "notes", ()) or ())
        if "fact_disclosure_not_recall" in debug_notes:
            return False

        norm = _normalize_recall_text(user_text)
        if best.intent == QueryIntent.RECALL_FACT:
            return any(
                marker in norm
                for marker in (
                    "toi ten gi",
                    "ten toi",
                    "toi ten la gi",
                    "nho ten toi",
                    "toi sinh thang may",
                    "thang sinh cua toi",
                    "sinh thang may",
                    "birthday month",
                    "toi dang o dau",
                    "toi hien o dau",
                    "toi o dau",
                    "truoc day toi o dau",
                    "toi tung o dau",
                )
            )
        if best.intent == QueryIntent.RECALL_COUNT:
            return any(marker in norm for marker in ("bao nhieu", "dem", "may cau"))
        if best.intent == QueryIntent.RECALL_SUMMARY:
            return any(marker in norm for marker in ("tom tat", "noi chung", "gan day"))
        if best.intent == QueryIntent.RECALL_TURN:
            if best.target.ordinal is not None or best.target.quantity is not None:
                return True
            if best.relation.relation != RelationRef.SELF:
                return True
            return any(
                marker in norm
                for marker in (
                    "nho",
                    "nho lai",
                    "cau hoi",
                    "cau tra loi",
                    "toi hoi gi",
                    "toi da noi gi",
                    "toi noi gi",
                    "em noi gi",
                    "em tra loi gi",
                    "truoc do",
                    "luc do",
                    "gan day",
                )
            )
        return False

    def _ensure_compiler(self) -> MemoryQueryCompiler:
        if self.compiler is not None:
            return self.compiler

        llm_client = _RuntimeMemoryQueryLLMClient.from_service(self.llm_service)
        llm_parser = MemoryQueryLLMParser(client=llm_client) if llm_client is not None else MemoryQueryLLMParser()
        self.compiler = MemoryQueryCompiler(llm_parser=llm_parser)
        return self.compiler

    def _execution_memory_core(self) -> Any:
        if self.memory_core is None and self.semantic_lookup is None:
            return None
        return _MemoryCoreProxy(
            base=self.memory_core,
            semantic_lookup=self.semantic_lookup,
            episodic_lookup=self.episodic_lookup,
        )

    def _build_decision(self, answer: RecallAnswer, *, compile_result: Any) -> Decision:
        reasoning_tags = (
            "answer_first",
            "memory_query",
            f"memory_surface:{answer.surface.value}",
            f"memory_source:{answer.source.value}",
        )
        return Decision(
            text=answer.text,
            intent="memory_recall",
            action="answer",
            animation="stand",
            reasoning_tags=reasoning_tags,
            should_speak=answer.should_speak,
            confidence=answer.confidence,
            direction=0,
            target_x=-1.0,
            bounce_action="",
            debug_trace=self._debug_trace(answer, compile_result=compile_result),
            next_animation="stand",
            parse_mode="memory_recall",
            system_action="",
            action_input="",
        )

    def _debug_trace(self, answer: RecallAnswer, *, compile_result: Any) -> str:
        debug = getattr(compile_result, "debug", None)
        pieces = [answer.debug_trace]
        if debug is not None:
            pieces.append(
                "memory_compile"
                f"|slots={int(getattr(debug, 'slot_hypotheses', 0) or 0)}"
                f"|semantic_conf={float(getattr(debug, 'semantic_confidence', 0.0) or 0.0):.2f}"
                f"|semantic_amb={float(getattr(debug, 'semantic_ambiguity', 1.0) or 1.0):.2f}"
                f"|llm={'1' if bool(getattr(debug, 'llm_called', False)) else '0'}"
                f"|llm_reason={str(getattr(debug, 'llm_reason', '') or 'none')}"
            )
            repair_applied = tuple(getattr(debug, "repair_applied", ()) or ())
            if repair_applied:
                pieces.append("repair=" + ",".join(repair_applied))
        return "|".join(part for part in pieces if part)


@dataclass(slots=True)
class _RecallOutcome:
    decision: Decision
    answer: RecallAnswer


class _MemoryCoreProxy:
    def __init__(
        self,
        *,
        base: Any = None,
        semantic_lookup: SemanticLookupFn | None = None,
        episodic_lookup: EpisodicLookupFn | None = None,
    ) -> None:
        self.base = base
        self.semantic_lookup_fn = semantic_lookup
        self.episodic_lookup_fn = episodic_lookup

    def lookup_fact(self, fact_key: str) -> Any:
        if self.base is not None:
            for method_name in ("lookup_fact", "get_fact", "semantic_lookup"):
                fn = getattr(self.base, method_name, None)
                if callable(fn):
                    try:
                        value = fn(fact_key)
                    except Exception:
                        value = None
                    if value is not None:
                        return value

        if self.semantic_lookup_fn is None:
            return None

        kind = _FACT_KEY_TO_MEMORY_KIND.get(str(fact_key or ""))
        if kind is None:
            return None

        try:
            return self.semantic_lookup_fn(kind)
        except Exception:
            return None

    def get_fact(self, fact_key: str) -> Any:
        return self.lookup_fact(fact_key)

    def semantic_lookup(self, fact_key: str) -> Any:
        return self.lookup_fact(fact_key)

    def recall(self, query: str = "") -> Any:
        if self.base is not None:
            recall = getattr(self.base, "recall", None)
            if callable(recall):
                return recall(query)
        if self.episodic_lookup_fn is None:
            return None
        return self.episodic_lookup_fn(query)

    def __getattr__(self, name: str) -> Any:
        if self.base is None:
            raise AttributeError(name)
        return getattr(self.base, name)


@dataclass(slots=True)
class _RuntimeMemoryQueryLLMClient(MemoryQueryLLMClient):
    service: Any

    @classmethod
    def from_service(cls, service: Any) -> Optional["_RuntimeMemoryQueryLLMClient"]:
        client = getattr(service, "client", None)
        if service is None or not callable(getattr(client, "create_chat_completion", None)):
            return None
        return cls(service=service)

    def complete_json(self, *, system: str, user: str, schema: dict[str, Any]) -> str:
        client = getattr(self.service, "client", None)
        if not callable(getattr(client, "create_chat_completion", None)):
            return ""

        schema_text = json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
        try:
            response = client.create_chat_completion(
                messages=[
                    {
                        "role": "system",
                        "content": f"{system}\nJSON schema:\n{schema_text}",
                    },
                    {"role": "user", "content": user},
                ],
                temperature=0.0,
                frequency_penalty=0.0,
                presence_penalty=0.0,
                max_tokens=320,
                response_format={"type": "json_object"},
                grammar=None,
            )
        except Exception:
            return ""

        extractor = getattr(self.service, "_extract_content", None)
        if callable(extractor):
            try:
                return str(extractor(response) or "")
            except Exception:
                return ""
        return _extract_response_text(response)


def _extract_response_text(response: Any) -> str:
    if isinstance(response, str):
        return response
    if not isinstance(response, dict):
        return ""

    direct = response.get("output_text") or response.get("text") or response.get("content")
    if isinstance(direct, str):
        return direct

    choices = response.get("choices")
    if isinstance(choices, list):
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            message = choice.get("message")
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str):
                    return content
            content = choice.get("content")
            if isinstance(content, str):
                return content

    candidates = response.get("candidates")
    if isinstance(candidates, list):
        for candidate in candidates:
            content = candidate.get("content") if isinstance(candidate, dict) else None
            if isinstance(content, str):
                return content

    return ""


def _normalize_recall_text(text: str) -> str:
    lowered = unicodedata.normalize("NFD", str(text or "").strip().lower())
    out_chars: list[str] = []
    for char in lowered:
        code = ord(char)
        if 0x0300 <= code <= 0x036F:
            continue
        if char == "đ":
            out_chars.append("d")
            continue
        if char.isalnum() or char in {" ", "_", "."}:
            out_chars.append(char)
        else:
            out_chars.append(" ")
    return " ".join("".join(out_chars).split())
