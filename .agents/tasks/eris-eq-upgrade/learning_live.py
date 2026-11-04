"""Exercise production observer/reducer against live LLM with isolated sandbox state."""
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace
import urllib.request

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "src"))
from llm.client import _attach_deepseek_json_schema
from runtime.ai_orchestrated.contracts import StateEvent
from runtime.ai_orchestrated.model_router import AIRuntimeModelRouter
from runtime.ai_orchestrated.state_reducer import StateReducer
from runtime.conversation.interaction_choice import record_delivered_choice, record_user_reaction

secrets = json.loads(Path("C:/Users/Gtvkun/Documents/eris/config/secrets.json").read_text("utf-8-sig"))["api_keys"]
key = secrets.get("ERIS_DS_OBSERVER_API_KEY") or secrets["ERIS_DS2API_API_KEY"]
wire = []


class Client:
    base_url = "http://127.0.0.1:5103/v1"
    model_name = "deepseek-flash"
    worker_role = "observer"

    def create_chat_completion(self, *, messages, response_format=None, **kwargs):
        payload = {"model": self.model_name, "messages": _attach_deepseek_json_schema(messages, response_format),
                   "thinking": {"type": "enabled"}, "response_format": {"type": "json_object"},
                   "max_tokens": kwargs.get("max_tokens", 1800)}
        started = time.monotonic()
        req = urllib.request.Request(self.base_url + "/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode(),
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
        with urllib.request.urlopen(req, timeout=90) as response:
            body = json.load(response)
        msg = body["choices"][0]["message"]
        wire.append({"content": msg.get("content"), "reasoning_chars": len(msg.get("reasoning_content", "") or ""),
                     "elapsed_seconds": round(time.monotonic() - started, 3)})
        return body


def main():
    os.environ["ERIS_POST_OBSERVER_DEEP_ENABLED"] = "0"
    sandbox = HERE / "sandbox"
    sandbox.mkdir(exist_ok=True)
    reducer = StateReducer(persist=lambda data: (sandbox / "state.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), "utf-8"))
    host = SimpleNamespace(ai_state_reducer=reducer)
    router = AIRuntimeModelRouter(SimpleNamespace(social_parser_client=Client()))
    results = []
    cases = [
        (2, "Tôi đang bực vì Kiro làm sai ý.", "Hỏi xem brief của user rõ đến đâu.",
         "Anh đã nói rõ ý cỡ nào? Kiro sai ý cụ thể ở đâu?",
         "Tôi đang tâm sự mà bạn lại hỏi kỹ thuật, càng nói càng mệt."),
        (6, "Giờ giúp tôi debug app crash nhé, cần gì cứ hỏi.", "Hỏi bằng chứng để debug.",
         "Gửi tôi stack trace, đoạn code liên quan và các bước tái hiện nhé.",
         "Đúng rồi, tôi cần được hỏi như vậy để biết gửi gì. Cảm ơn, rất hữu ích."),
    ]
    try:
        for seq, original, goal, spoken, reaction in cases:
            did, ref = f"sandbox:delivery:{seq}", f"sandbox:user:{seq + 1}"
            record_delivered_choice(host, choice={}, delivery_id=did, session_id="eq-sandbox",
                                    turn_seq=seq, goal=goal, assistant_text=spoken, user_text=original)
            record_user_reaction(host, session_id="eq-sandbox", turn_seq=seq + 1, turn_ref=ref,
                                 user_text=reaction, now=time.time(), previous_assistant_turn_seq=seq)
            assert reducer.wait_idle()
            state = reducer.snapshot().to_dict()
            state["conversation_session_id"] = "eq-sandbox"
            observation = router.observe_completed_turn(
                turn_id=f"sandbox:reply:{seq + 2}", turn_seq=seq + 2,
                user_text=reaction, assistant_text="Ừ, tôi nghe rồi.",
                recent_history=({"role": "assistant", "content": spoken},),
                state_summary=state, timeout_seconds=90)
            reducer.submit(StateEvent.from_observation(observation))
            assert reducer.wait_idle()
            learned = reducer.snapshot().identity
            results.append({"source_delivery": did, "reaction_ref": ref,
                            "consequence": observation.consequence.to_dict(),
                            "pending_ids": [item.strategy_use_id for item in learned.pending_strategies],
                            "experiences": list(learned.strategies["root_move"].experiences),
                            "aggregate_utility": learned.strategies["root_move"].utility})
            print(did, "remaining", len(learned.pending_strategies), "outcome", observation.consequence.outcome,
                  "reinforcement", observation.consequence.reinforcement, flush=True)
    finally:
        reducer.close()
        (HERE / "learning_live_results.json").write_text(json.dumps({"results": results, "wire": wire},
            ensure_ascii=False, indent=2), "utf-8")


if __name__ == "__main__":
    main()
