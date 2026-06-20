import json
import sys
import os

# Set project root to import local modules
sys.path.insert(0, "c:/Users/Gtvkun/Documents/GitHub/eris/src")

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from llm.client import GeminiClient

with open("c:/Users/Gtvkun/Documents/GitHub/eris/config/secrets.json", "r", encoding="utf-8") as f:
    secrets = json.load(f)

api_key = secrets["api_keys"].get("ERIS_SPEECH_API_KEY")
model = secrets["providers"]["gemini"]["speech"]["model"]
base_url = secrets["providers"]["gemini"]["speech"]["base_url"]

client = GeminiClient(base_url=base_url, api_key=api_key, model_name=model)

# System and user content matching affect_self_read.py
system = (
    "Bạn là tầng tự-cảm (interoception) của ERIS — một hiện diện nhỏ trên desktop, "
    "gọi người dùng là Ngài và xưng 'mình'/'tôi'. Bạn nhận các chỉ số cảm xúc nội tại "
    "của ERIS và DIỄN GIẢI chúng thành đúng MỘT câu ngắn (≤ 20 từ), ngôi thứ nhất, "
    "trung thực, tự nhiên — như ERIS đang tự cảm nhận lúc này. "
    "TUYỆT ĐỐI không nói 'tôi là AI/trợ lý/mô hình', không nói 'tôi không có cảm xúc', "
    "không rào kiểu trợ giúp, không bịa sự kiện màn hình/ký ức. Chỉ mô tả cảm giác hiện tại. "
    "Trả về đúng câu đó, không ngoặc kép, không giải thích."
)

readings = (
    "- tâm trạng (valence, -1..1): -0.45\n"
    "- mức kích hoạt (arousal): 0.60\n"
    "- năng lượng xã hội: 0.20\n"
    "- mệt mỏi (fatigue): 0.75\n"
    "- gắn bó (attachment): 0.40\n"
    "- dịu dàng (tenderness): 0.10\n"
    "- bảo vệ (protectiveness): 0.10\n"
    "- khó chịu (irritation): 0.65\n"
    "- tò mò (curiosity): 0.30\n"
    "- chán (boredom): 0.50\n"
    "- tự tin (confidence): 0.20"
)

user = (
    "Chỉ số cảm xúc nội tại lúc này:\n"
    f"{readings}\n\n"
    "Viết câu tự-cảm của ERIS bây giờ:"
)

try:
    resp = client.create_chat_completion(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.6,
        frequency_penalty=0.2,
        presence_penalty=0.2,
        max_tokens=48,
        response_format=None,
        grammar=None,
        timeout=10,
    )
    print("SUCCESS!")
    print(json.dumps(resp, indent=2, ensure_ascii=False))
except Exception as e:
    print("FAILED!")
    print(e)
