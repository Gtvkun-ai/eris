import os, sys
sys.path.insert(0, r"c:\Users\Gtvkun\Documents\GitHub\eris\.worktrees\rescue\src")

import llm.client as client_module
from llm.raw_trace import worker_role_context

captured = {}
def fake_post(**kwargs):
    captured.clear(); captured.update(kwargs)
    class _R:
        status_code = 200
        def json(self):
            return {"choices":[{"message":{"content":"{}"}}]}
        def raise_for_status(self): pass
        text = "{}"
    return _R()

client_module._brokered_post = fake_post
os.environ["ERIS_EXECUTIVE_THINKING_DISABLED"] = "1"

def mk():
    return client_module.OpenAICompatibleClient(
        base_url="http://localhost:6011/v1", api_key="sk-test",
        model_name="deepseek-v4-flash", key_pool=None)

def call(c):
    c.create_chat_completion(messages=[{"role":"user","content":"hi"}],
                             temperature=0.4, frequency_penalty=0.0,
                             presence_penalty=0.0, max_tokens=64)

# 1) bare call, no role context
c = mk(); call(c)
print("BARE thinking =", captured.get("json",{}).get("thinking"))

# 2) inside executive role context (mimics JsonlWorkerClient wrapper)
c = mk()
with worker_role_context("executive"):
    call(c)
print("CTX executive thinking =", captured.get("json",{}).get("thinking"))

# 3) attribute set directly on client (the getattr(self,...) path)
c = mk(); c.worker_role = "executive"; call(c)
print("ATTR executive thinking =", captured.get("json",{}).get("thinking"))
