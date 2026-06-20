import json
import requests
import sys
import time

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

secrets_path = "c:/Users/Gtvkun/Documents/GitHub/eris/config/secrets.json"
with open(secrets_path, "r", encoding="utf-8") as f:
    secrets = json.load(f)

# Collect all keys to test
keys_to_test = []

def add_key(key, name):
    if key and key not in [k for k, _ in keys_to_test]:
        keys_to_test.append((key, name))

add_key(secrets["api_keys"].get("ERIS_REMOTE_API_KEY"), "ERIS_REMOTE_API_KEY")
add_key(secrets["api_keys"].get("ERIS_SPEECH_API_KEY"), "ERIS_SPEECH_API_KEY")

fallbacks = secrets["api_keys"].get("ERIS_PRIVATE_MIND_FALLBACK_API_KEYS", [])
for i, key in enumerate(fallbacks):
    add_key(key, f"FALLBACK_KEY_{i}")

print("=== START TESTING GEMINI API KEYS WITH DELAYS ===")
print(f"Total unique keys to test: {len(keys_to_test)}\n")

for key, name in keys_to_test:
    masked_key = key[:10] + "..." + key[-5:] if len(key) > 15 else key
    print(f"Testing {name} ({masked_key}):")
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
    payload = {
        "contents": [
            {"role": "user", "parts": [{"text": "Hello"}]}
        ],
        "generationConfig": {
            "maxOutputTokens": 5
        }
    }
    
    try:
        resp = requests.post(
            url,
            headers={
                "x-goog-api-key": key,
                "Content-Type": "application/json"
            },
            json=payload,
            timeout=5
        )
        if resp.status_code == 200:
            print("  -> STATUS: VALID (200 OK)")
        else:
            print(f"  -> STATUS: INVALID (HTTP {resp.status_code})")
            try:
                err_msg = resp.json().get("error", {}).get("message", "")
                print(f"     Reason: {err_msg}")
            except Exception:
                print(f"     Response: {resp.text[:150]}")
    except Exception as e:
        print(f"  -> STATUS: FAILED TO CONNECT")
        print(f"     Error: {e}")
    
    # Delay to avoid IP-level rate-limiting / throttling
    time.sleep(2.0)
    print("-" * 50)
