import asyncio, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, "services/gitpilot")
from gitpilot.gatekeeper import classify_request

cases = [
    "xin chao",
    "xin chào",
    "hello",
    "cam on",
    "fix the timeout bug in inference_broker.py",
    "explain how the dialog system works",
    "add a new function to validate user input",
    "tai sao orchestrator bi crash",
    "what is the difference between A and B",
    "chay thu cai script nay",
    "sua loi trong file agentic.py",
    "giai thich kien truc cua repo nay",
]

async def test():
    for msg in cases:
        d = await classify_request(msg)
        fp = "FAST" if d.fast_path else "LLM "
        print(f"{d.route:<18} {d.confidence:.2f}  [{fp}]  {msg!r}")

asyncio.run(test())
