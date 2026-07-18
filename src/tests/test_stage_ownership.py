from __future__ import annotations

from types import SimpleNamespace

from runtime.stage_ownership import stage_channel_blocked, stage_ownership_for


def test_stage_ownership_blocks_only_declared_channels_and_owner_can_surface():
    owner = SimpleNamespace()
    lease = stage_ownership_for(owner)

    assert lease.acquire(owner_id="call-1", kind="exclusive_call", blocks=("autonomous",)) is True
    assert stage_channel_blocked(owner, "autonomous") is True
    assert stage_channel_blocked(owner, "chat") is False
    assert stage_channel_blocked(owner, "autonomous", requester_id="call-1") is False
    assert lease.release("someone-else") is False
    assert lease.release("call-1") is True
    assert stage_channel_blocked(owner, "autonomous") is False
