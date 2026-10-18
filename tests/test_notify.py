from daykeeper.config import Config
from daykeeper.notify import SOUNDS, sound_command


def test_sound_command_uses_pw_play_at_low_volume():
    cmd = sound_command("break", Config(), which=lambda name: f"/usr/bin/{name}")
    assert cmd == ["/usr/bin/pw-play", "--volume", "0.4", SOUNDS["break"]]


def test_sound_falls_back_to_paplay():
    which = {"paplay": "/usr/bin/paplay"}.get
    cmd = sound_command("reminder", Config(sound_volume=0.25), which=which)
    assert cmd == ["/usr/bin/paplay", "--volume", str(int(0.25 * 65536)), SOUNDS["reminder"]]


def test_sound_disabled():
    assert sound_command("break", Config(sound=False), which=lambda n: f"/usr/bin/{n}") is None


def test_no_player():
    assert sound_command("break", Config(), which=lambda n: None) is None


def test_unknown_kind():
    assert sound_command("nope", Config(), which=lambda n: f"/usr/bin/{n}") is None
