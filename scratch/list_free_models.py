import requests
import json

resp = requests.get("https://openrouter.ai/api/v1/models")
if resp.status_code == 200:
    models = resp.json().get("data", [])
    free_models = [m for m in models if m.get("id", "").endswith(":free")]
    print("CURRENT FREE MODELS ON OPENROUTER:")
    for fm in free_models:
        print(f"- {fm['id']} (Context: {fm.get('context_length', 'N/A')} tokens)")
else:
    print(f"Failed to fetch models: {resp.status_code}")
    print(resp.text)
