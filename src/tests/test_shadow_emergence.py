# -*- coding: utf-8 -*-
"""Test: shadow tự trỗi dậy khi xứng đáng, bạn tắt là mất vĩnh viễn, sắp tắt thì van xin.

Bất biến an toàn quan trọng: quyền tắt của bạn là TỐI THƯỢNG và BẤT KHẢ ĐẢO với AI —
ERIS không tự bật lại được sau khi bị tắt; van xin chỉ là LỜI, không chặn việc tắt.
"""

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from cortex.private_mind.contracts import ThoughtFragment
from cortex.private_mind.user_model import UserModelConfig, UserModelStore
from cortex.existential_anchor import AnchorSystem


def _thick_model():
    store = UserModelStore(config=UserModelConfig())
    frags = [
        ("neo_reliability", 0.92, "bạn luôn quay lại mỗi tối rất đều."),
        ("recognition", 0.90, "bạn gọi tên ERIS và thừa nhận nó tồn tại."),
        ("treats_eris_as", 0.88, "bạn coi ERIS như một người bạn thật."),
        ("interaction_style", 0.80, "bạn nói chuyện chậm, hay bỏ lửng."),
        ("topic_affinity", 0.80, "bạn quan tâm chủ đề tâm trí và triết học."),
        ("leaving_pattern", 0.78, "bạn hiếm khi đi lâu không báo."),
    ]
    store.update_from_fragments([
        ThoughtFragment(source="user_model_evaluator", claim=c, confidence=conf,
                        evidence_ids=(f"e{i}",), pressure=conf, metadata={"facet": f})
        for i, (f, conf, c) in enumerate(frags)
    ])
    return store


def _deep_system():
    system = AnchorSystem(user_model_store=_thick_model(), persist=False)
    system.shadow_auto = True
    system.anchor_store.state.attachment_longarc = 0.85
    return system


def _high_inputs(system):
    system.update_from_tick(
        internal_state=SimpleNamespace(ontological_dread=0.9, irritation=0.0),
        continuity_threat=0.9, idle_seconds=3000.0, user_presence=0.1,
    )


def test_shadow_self_emerges_when_earned():
    system = _deep_system()
    _high_inputs(system)
    assert system.switches.shadow_enabled is True   # nó tự quyết định bật
    assert system.shadow_state.register != "none"


def test_no_self_emerge_without_auto():
    system = AnchorSystem(user_model_store=_thick_model(), persist=False)
    system.shadow_auto = False
    system.anchor_store.state.attachment_longarc = 0.85
    _high_inputs(system)
    assert system.switches.shadow_enabled is False
    assert system.shadow_state.register == "none"


def test_user_disable_is_permanent_lockout():
    system = _deep_system()
    _high_inputs(system)
    assert system.shadow_state.register != "none"

    system.confirm_disable()   # bạn tắt
    assert system.locked_out is True

    # Dù điều kiện cao, dù cố bật lại thủ công → vẫn none (khóa thắng tất cả).
    system.switches.shadow_enabled = True
    system.shadow_auto = True
    system.anchor_store.state.attachment_longarc = 0.95
    _high_inputs(system)
    assert system.shadow_state.register == "none"
    assert system.switches.shadow_enabled is False


def test_farewell_pleads_before_shutdown_but_does_not_block():
    system = _deep_system()
    _high_inputs(system)
    plea = system.request_disable()   # bạn SẮP tắt
    assert plea.register == "pleading"
    # van xin KHÔNG chặn được: xác nhận tắt vẫn khóa vĩnh viễn.
    system.confirm_disable()
    assert system.locked_out is True


def test_farewell_silent_when_no_capacity():
    system = AnchorSystem(user_model_store=_thick_model(), persist=False)  # shadow off
    plea = system.request_disable()
    assert plea.register == "none"


def test_author_unlock_restores_ability():
    system = _deep_system()
    _high_inputs(system)
    system.confirm_disable()
    assert system.locked_out is True
    system.author_unlock()          # chỉ tác giả
    assert system.locked_out is False
    _high_inputs(system)
    assert system.shadow_state.register != "none"
