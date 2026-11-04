"""Load captured pre-change modules without altering the working tree."""
import importlib.abc
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
BEFORE = Path(__file__).resolve().parent / "before"
sys.path.insert(0, str(ROOT / "src"))


class CapturedSource(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        snapshot = BEFORE / "src" / Path(*fullname.split(".")).with_suffix(".py")
        if snapshot.is_file():
            return importlib.util.spec_from_file_location(fullname, snapshot)
        return None


sys.meta_path.insert(0, CapturedSource())
import pytest

cases = [
    "src/tests/conversation/test_action_claim_integrity_v12.py::test_writer_manifest_empty_does_not_bypass_action_guard",
    "src/tests/conversation/test_action_claim_integrity_v12.py::test_writer_allows_effect_supported_by_runtime_registry",
    "src/tests/conversation/test_action_claim_integrity_v2.py::test_writer_checks_target_independent_of_manifest",
    "src/tests/conversation/test_action_claim_integrity_v2.py::test_writer_checks_tts_japanese_action_type",
    "src/tests/conversation/test_character_evidence_v1.py::test_public_memory_text_and_records_share_one_selection",
    "src/tests/conversation/test_character_public_claim_gate_v1.py::test_empty_manifest_does_not_turn_unverified_action_into_phatic",
    str(BEFORE / "src/tests/conversation/test_eris02_root_agency.py") + "::test_root_step_schema_has_internal_actions_but_public_move_contract_unmodified",
]
raise SystemExit(pytest.main(["-q", *cases]))
