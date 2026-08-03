# -*- coding: utf-8 -*-
from runtime.ai_orchestrated.opening_move_catalog import (
    get_opening_move,
    opening_move_catalog,
    validate_opening_move_catalog,
)


def test_opening_move_catalog_is_valid_and_behavior_level() -> None:
    catalog = opening_move_catalog()
    assert len(catalog) >= 10
    assert validate_opening_move_catalog(catalog) == ()
    assert len({item.family for item in catalog}) == len(catalog)
    assert get_opening_move("mock_indifference").structure[0] == "recognition"


def test_unknown_move_degrades_to_simple_recognition() -> None:
    assert get_opening_move("con người lại đặt tên sai").family == "simple_recognition"
