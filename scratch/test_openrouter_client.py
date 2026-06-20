import json
import sys
import os

# Set project root to import local modules
sys.path.insert(0, "c:/Users/Gtvkun/Documents/GitHub/eris/src")

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from llm.client import OpenAICompatibleClient
from llm.key_pool import get_key_pool
from eris_secrets import apply_secrets_to_environ

# Initialize environment from secrets
apply_secrets_to_environ()

with open("c:/Users/Gtvkun/Documents/GitHub/eris/config/secrets.json", "r", encoding="utf-8") as f:
    secrets = json.load(f)

profile = secrets["providers"]["openai_compatible"]["remote_main"]
api_key = profile.get("api_key")  # Will be None now
model = profile.get("model")
base_url = profile.get("base_url")

pool = get_key_pool("groq")  # This pool loads ERIS_GROQ_API_KEY and ERIS_GROQ_FALLBACK_API_KEYS

print(f"Testing OpenRouter with Key Pool Rotation:")
print(f"Base URL: {base_url}")
print(f"Model: {model}")
print(f"Original API Key in profile: {api_key}")
print(f"Pool size: {pool.size}")
print(f"Current Key in Pool: {pool.current_key()[:10]}...")

client = OpenAICompatibleClient(base_url=base_url, api_key=api_key, model_name=model, key_pool=pool)

try:
    resp = client.create_chat_completion(
        messages=[
            {"role": "system", "content": "You are a helpful assistant. Keep your response very brief (less than 10 words)."},
            {"role": "user", "content": "Hello! What is your model name?"},
        ],
        temperature=0.6,
        frequency_penalty=0.0,
        presence_penalty=0.0,
        max_tokens=48,
        response_format=None,
        grammar=None,
        timeout=15,
    )
    print("SUCCESS!")
    print(json.dumps(resp, indent=2, ensure_ascii=False))
except Exception as e:
    print("FAILED!")
    print(e)
