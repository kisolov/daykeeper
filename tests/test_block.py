from datetime import datetime, timedelta

import pytest

from daykeeper.block import Block, BlockError, NetError
from daykeeper.config import Config
from daykeeper.service import Service, ServiceError


class FakeNet:
    def __init__(self):
        self.calls: list[bool] = []
        self.fail = False

    def set_blocked(self, blocked: bool) -> None:
        if self.fail:
            raise NetError("sudo: a password is required")
        self.calls.append(blocked)


@pytest.fixture
def net():
    return FakeNet()


@pytest.fixture
def block(db, clock, net):
    return Block(db, Config(block_daily_limit=2), clock, net)


def unlock(block):
    code = block.challenge()["code"]
    return block.unlock(code)


def test_starts_blocked(block):
    st = block.status()
    assert st["blocked"] is True and st["until"] is None
    assert st["used_today"] == 0 and st["daily_limit"] == 2 and st["minutes"] == 60


def test_challenge_code_is_long_random(block):
    a = block.challenge()["code"].replace(" ", "")
    b = block.challenge()["code"].replace(" ", "")
    assert len(a) == 48 and a != b


def test_unlock_with_right_code(block, net, clock):
    st = unlock(block)
    assert net.calls == [False]
    assert st["blocked"] is False and st["until"] == "10:00" and st["used_today"] == 1


def test_code_typed_with_spaces_and_caps_is_accepted(block, net):
    code = block.challenge()["code"]
    block.unlock("  " + code.upper() + " ")
    assert net.calls == [False]


def test_wrong_code_keeps_block_and_burns_challenge(block, net):
    code = block.challenge()["code"]
    with pytest.raises(BlockError, match="неверный"):
        block.unlock("nope")
    with pytest.raises(BlockError, match="сначала"):
        block.unlock(code)
    assert net.calls == []
    assert block.status()["used_today"] == 0


def test_unlock_without_challenge(block):
    with pytest.raises(BlockError, match="сначала"):
        block.unlock("whatever")


def test_challenge_expires(block, clock):
    code = block.challenge()["code"]
    clock.advance(11 * 60)
    with pytest.raises(BlockError, match="устарел"):
        block.unlock(code)


def test_daily_limit(block, clock):
    unlock(block)
    block.lock()
    unlock(block)
    block.lock()
    with pytest.raises(BlockError, match="лимит"):
        block.challenge()
    clock.advance(24 * 3600)
    assert block.challenge()["code"]


def test_challenge_while_unlocked_is_refused(block):
    unlock(block)
    with pytest.raises(BlockError, match="уже"):
        block.challenge()


def test_tick_relocks_after_an_hour(block, net, clock):
    unlock(block)
    clock.advance(59 * 60)
    assert block.tick() is False and net.calls == [False]
    clock.advance(60)
    assert block.tick() is True and net.calls == [False, True]
    assert block.status()["blocked"] is True
    assert block.tick() is False and net.calls == [False, True]


def test_manual_lock_ends_unlock_early(block, net):
    unlock(block)
    st = block.lock()
    assert st["blocked"] is True and net.calls == [False, True]


def test_net_failure_on_unlock_is_not_counted(block, net):
    code = block.challenge()["code"]
    net.fail = True
    with pytest.raises(BlockError, match="сеть"):
        block.unlock(code)
    assert block.status()["used_today"] == 0 and block.status()["blocked"] is True


def test_relock_retries_with_backoff(block, net, clock):
    unlock(block)
    clock.advance(3600)
    net.fail = True
    assert block.tick() is False
    net.fail = False
    clock.advance(5)
    assert block.tick() is False and net.calls == [False]
    clock.advance(30)
    assert block.tick() is True and net.calls == [False, True]


def test_enforce_restores_state_after_restart(db, clock, net):
    b = Block(db, Config(), clock, net)
    unlock(b)
    fresh = FakeNet()
    Block(db, Config(), clock, fresh).enforce()
    assert fresh.calls == [False]
    clock.advance(3600)
    later = FakeNet()
    Block(db, Config(), clock, later).enforce()
    assert later.calls == [True]


def test_service_exposes_block(db, clock, net):
    svc = Service(db, Config(), clock, net=net)
    code = svc.call("block_challenge")["code"]
    assert svc.call("block_unlock", code=code)["blocked"] is False
    assert svc.live_state()["block"]["blocked"] is False
    with pytest.raises(ServiceError) as e:
        svc.call("block_challenge")
    assert e.value.code == "invalid"
    clock.advance(3600)
    svc.tick()
    assert svc.call("block_status")["blocked"] is True
