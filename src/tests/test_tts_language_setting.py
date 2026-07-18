# -*- coding: utf-8 -*-
"""Hồi quy cho setting ngôn ngữ TTS bị launcher ép về tiếng Việt."""

from __future__ import annotations

import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import eris_secrets
from runtime import tts_engine


class RuntimePreferenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_root = os.environ.get("ERIS_PROJECT_ROOT")
        self._old_language = os.environ.get("ERIS_TTS_LANGUAGE")
        self._old_disable = os.environ.get("ERIS_DISABLE_DOTENV")
        self._old_prelocalize = os.environ.get("ERIS_TTS_PRELOCALIZE_JA")
        os.environ.pop("ERIS_DISABLE_DOTENV", None)

    def tearDown(self) -> None:
        for name, value in (
            ("ERIS_PROJECT_ROOT", self._old_root),
            ("ERIS_TTS_LANGUAGE", self._old_language),
            ("ERIS_DISABLE_DOTENV", self._old_disable),
            ("ERIS_TTS_PRELOCALIZE_JA", self._old_prelocalize),
        ):
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        eris_secrets._CONFIG_SOURCE.pop("ERIS_TTS_LANGUAGE", None)

    def test_dotenv_language_overrides_launcher_default_and_accepts_bom(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            Path(temp_dir, ".env").write_text("\ufeffERIS_TTS_LANGUAGE=ja\n", encoding="utf-8")
            os.environ["ERIS_PROJECT_ROOT"] = temp_dir
            os.environ["ERIS_TTS_LANGUAGE"] = "vi"  # default bị launcher chèn

            applied = eris_secrets.refresh_runtime_preferences("ERIS_TTS_LANGUAGE")

            self.assertEqual(applied, {"ERIS_TTS_LANGUAGE": "ja"})
            self.assertEqual(os.environ["ERIS_TTS_LANGUAGE"], "ja")
            self.assertEqual(eris_secrets.config_source("ERIS_TTS_LANGUAGE"), ".env(runtime-preference)")


class LanguageNormalizationTests(unittest.TestCase):
    def test_japanese_aliases_normalize_to_ja(self) -> None:
        for value in ("ja", "jp", "Japanese", "ja-JP", "日本語"):
            with self.subTest(value=value):
                self.assertEqual(tts_engine._normalize_language_hint(value), "ja")


class JapanesePrelocalizeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_prelocalize = os.environ.get("ERIS_TTS_PRELOCALIZE_JA")

    def tearDown(self) -> None:
        if self._old_prelocalize is None:
            os.environ.pop("ERIS_TTS_PRELOCALIZE_JA", None)
        else:
            os.environ["ERIS_TTS_PRELOCALIZE_JA"] = self._old_prelocalize

    def test_stage_localize_runtime_setting_enables_prelocalize_by_default(self) -> None:
        os.environ.pop("ERIS_TTS_PRELOCALIZE_JA", None)
        with patch("runtime.runtime_settings_store.runtime_bool", return_value=True) as runtime_bool:
            self.assertTrue(tts_engine._prelocalize_japanese_enabled())
        runtime_bool.assert_called_once_with("tts", "stage_localize", default=True)

    def test_explicit_prelocalize_env_overrides_runtime_setting(self) -> None:
        os.environ["ERIS_TTS_PRELOCALIZE_JA"] = "0"
        with patch("runtime.runtime_settings_store.runtime_bool", return_value=True) as runtime_bool:
            self.assertFalse(tts_engine._prelocalize_japanese_enabled())
        runtime_bool.assert_not_called()


class TtsAttemptPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_attempts = os.environ.get("ERIS_TTS_MAX_ATTEMPTS")

    def tearDown(self) -> None:
        if self._old_attempts is None:
            os.environ.pop("ERIS_TTS_MAX_ATTEMPTS", None)
        else:
            os.environ["ERIS_TTS_MAX_ATTEMPTS"] = self._old_attempts

    def test_tts_attempts_default_to_full_pool(self) -> None:
        os.environ.pop("ERIS_TTS_MAX_ATTEMPTS", None)
        self.assertGreaterEqual(tts_engine._tts_max_attempts(), 10_000)

    def test_tts_attempts_accept_explicit_numeric_limit(self) -> None:
        os.environ["ERIS_TTS_MAX_ATTEMPTS"] = "3"
        self.assertEqual(tts_engine._tts_max_attempts(), 3)


class TtsRefreshTests(unittest.TestCase):
    def test_global_japanese_language_overrides_vietnamese_request_contract(self) -> None:
        req = tts_engine._SpeakRequest(
            text="Xin chào",
            language_hint="vi",
            locale="vi-VN",
        )
        worker = object.__new__(tts_engine._TtsWorker)
        worker._language_hint = "ja"

        self.assertEqual(worker._request_language(req), "ja")
        self.assertEqual(worker._request_locale(req), "ja-JP")

    def test_worker_is_rebuilt_when_language_changes(self) -> None:
        class FakeWorker:
            def __init__(self, voice="", model="", language="") -> None:
                self.voice = voice
                self.model = model
                self.language = language
                self.stopped = False

            def shutdown(self) -> None:
                self.stopped = True

        class FakeManager:
            def __init__(self) -> None:
                self.stopped = False

            def shutdown(self) -> None:
                self.stopped = True

        old_worker = FakeWorker()
        manager = FakeManager()
        engine = object.__new__(tts_engine.TtsEngine)
        engine._worker = old_worker
        engine._ok = True
        engine._closed = False
        engine._config_lock = threading.RLock()
        engine._config_signature = "Aoede|model|vi"
        engine.task_manager = manager

        with (
            patch("eris_secrets.refresh_runtime_preferences", return_value={"ERIS_TTS_LANGUAGE": "ja"}),
            patch.object(tts_engine, "_voice", return_value="Aoede"),
            patch.object(tts_engine, "_model", return_value="model"),
            patch.object(tts_engine, "_language_hint", return_value="ja"),
            patch.object(tts_engine, "_TtsWorker", FakeWorker),
        ):
            changed = engine.refresh_configuration()

        self.assertTrue(changed)
        self.assertTrue(old_worker.stopped)
        self.assertTrue(manager.stopped)
        self.assertIsNone(engine.task_manager)
        self.assertEqual(engine._worker.language, "ja")
        self.assertEqual(engine._config_signature, "Aoede|model|ja")


if __name__ == "__main__":
    unittest.main()
