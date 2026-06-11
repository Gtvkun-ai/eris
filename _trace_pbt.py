import sys, os
sys.path.insert(0, os.path.abspath('src'))
import requests
from runtime.private_mind_model_adapter import PrivateMindModelAdapterConfig, RuntimePrivateMindModelAdapter
from cortex.private_mind.contracts import EvidenceDossier


def _make_http_error(status_code):
    response = requests.Response()
    response.status_code = status_code
    response.reason = "Internal Server Error"
    response.url = "https://fake.api/generateContent"
    return requests.HTTPError(f"{status_code} Error", response=response)


class Fake500:
    def __init__(self):
        self.call_count = 0
    def create_chat_completion(self, **kwargs):
        self.call_count += 1
        raise _make_http_error(500)


cfg = PrivateMindModelAdapterConfig(provider="gemini", enabled=True, api_key="k")
ad = RuntimePrivateMindModelAdapter(config=cfg, llm_service=None, logger=None)
fake = Fake500()
ad._provider_client = fake

# Trace _chat_json_once directly
msgs = [{"role": "user", "content": "hi"}]
once = ad._chat_json_once(msgs, max_tokens=100, temperature=0.5, response_schema=None)
print("once.error_kind=", repr(once.error_kind), "once.error=", repr(once.error))
print("after once, call_count=", fake.call_count)

fake.call_count = 0
retry = ad._chat_json_with_transient_retry(msgs, max_tokens=100, temperature=0.5, response_schema=None)
print("retry wrapper call_count=", fake.call_count, "result.error_kind=", repr(retry.error_kind))

fake.call_count = 0
res = ad.evaluate_fragment("intent_evaluator", EvidenceDossier(dossier_id="t"))
print("evaluate_fragment call_count=", fake.call_count, "transient_streak=", ad._transient_streak)
