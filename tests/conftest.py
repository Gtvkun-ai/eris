# -*- coding: utf-8 -*-
"""tests/conftest.py — shared test import helper.

Chèn thư mục ``src`` vào ``sys.path`` để các test có thể import ``cortex.*``
(và các package khác trong ``src``) mà không cần cài đặt package. Theo đúng
quy ước đã dùng trong ``tests/test_pbt_*.py``:

    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

Vì ``conftest.py`` được pytest tự nạp trước khi thu thập test, việc chèn đường
dẫn ở đây áp dụng cho mọi test trong thư mục ``tests/`` — kể cả bộ test Phase 2
(``test_world_scene_builder.py``, ``test_sociocultural_context.py``,
``test_meaning_hypothesis.py``, ``test_pragmatic_intent.py``,
``test_theory_of_mind.py``, ``test_overread_brake.py``,
``test_phase2_integration.py``).
"""

from __future__ import annotations

import os
import sys

_SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))

if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

# Thư mục ``tests`` cũng được chèn vào sys.path để các test import được module
# helper dùng chung ``phase2_strategies`` (hypothesis strategies của Phase 2)
# dưới dạng ``from phase2_strategies import frames, ...``.
_TESTS_DIR = os.path.abspath(os.path.dirname(__file__))

if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

# Cô lập test khỏi mạng/model thật: private-mind API (synthesis→Gemini/local) và
# các mạch LLM nền có thể được bật qua config/secrets.json hoặc .env trong môi
# trường dev. Trong test, ép TẮT để không gọi mạng (gây treo/flaky) hay nạp model
# GPU. Dùng gán cứng (không setdefault) để thắng mọi cấu hình môi trường.
# apply_secrets_to_environ() dùng setdefault nên sẽ tôn trọng các giá trị này.
os.environ["ERIS_PRIVATE_MIND_API_ENABLED"] = "0"
os.environ["ERIS_PRIVATE_MIND_FRAGMENT_PROVIDER"] = ""
os.environ["ERIS_PRIVATE_MIND_FRAGMENT_FREETEXT"] = "0"
os.environ["ERIS_GUARDS_WARN_ONLY"] = "0"
# Không bao giờ dựng engine local (llama-cpp nạp gguf GPU) trong test.
os.environ["ERIS_LOCAL_LLM_ENGINE"] = "ollama"

# Cô lập test khỏi file .env của repo: loader .env mới (eris_secrets.load_env_file)
# chỉ chạy ở runtime thật. Trong test, tắt để không kéo toggle production (vision
# facts, observer LLM, llamacpp…) vào làm sai/flaky các assertion.
os.environ["ERIS_DISABLE_DOTENV"] = "1"
os.environ["ERIS_DEPTH_AUTO_ENABLE"] = "0"
os.environ["ERIS_DEPTH_FLAGS_PATH"] = os.path.join(_TESTS_DIR, "non_existent_depth_flags_test_temp.json")
