import json
import requests
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

with open("c:/Users/Gtvkun/Documents/GitHub/eris/config/secrets.json", "r", encoding="utf-8") as f:
    secrets = json.load(f)

# Thử với ERIS_REMOTE_API_KEY (Key này dành cho Main)
api_key = secrets["api_keys"].get("ERIS_REMOTE_API_KEY")
model = secrets["providers"]["gemini"]["speech"]["model"]
base_url = secrets["providers"]["gemini"]["speech"]["base_url"]

print(f"Testing with ERIS_REMOTE_API_KEY: {api_key[:10]}...")
url = f"{base_url}/models/{model}:generateContent"

payload = {
    "contents": [
        {"role": "user", "parts": [{"text": "Xin chào"}]}
    ],
    "generationConfig": {
        "temperature": 0.6,
        "maxOutputTokens": 48
    }
}

resp = requests.post(
    url,
    headers={
        "x-goog-api-key": api_key,
        "Content-Type": "application/json"
    },
    json=payload
)

print(f"Status Code: {resp.status_code}")
print("Response Body:")
print(resp.text)
