from daykeeper.config import load_config


def test_config_defaults(tmp_path, monkeypatch):
    monkeypatch.delenv("DAYKEEPER_TG_TOKEN", raising=False)
    c = load_config(tmp_path / "none.toml")
    assert (c.work_min, c.break_min) == (47, 13)
    assert c.tg_token is None and c.tg_chat_id is None


def test_config_env_token(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYKEEPER_TG_TOKEN", "t")
    assert load_config(tmp_path / "none.toml").tg_token == "t"


def test_config_file(tmp_path, monkeypatch):
    monkeypatch.delenv("DAYKEEPER_TG_TOKEN", raising=False)
    p = tmp_path / "c.toml"
    p.write_text('work_min = 25\nbreak_min = 5\n[telegram]\ntoken = "abc"\nchat_id = 42\n')
    c = load_config(p)
    assert (c.work_min, c.break_min, c.tg_token, c.tg_chat_id) == (25, 5, "abc", 42)


def test_config_path_overrides(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYKEEPER_DB", str(tmp_path / "d.db"))
    monkeypatch.setenv("DAYKEEPER_SOCKET", str(tmp_path / "s.sock"))
    c = load_config(tmp_path / "none.toml")
    assert c.db_path == tmp_path / "d.db" and c.socket_path == tmp_path / "s.sock"


def test_sound_defaults(tmp_path):
    c = load_config(tmp_path / "none.toml")
    assert c.sound is True and c.sound_volume == 0.4


def test_sound_config(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text("[sound]\nenabled = false\nvolume = 0.2\n")
    c = load_config(p)
    assert c.sound is False and c.sound_volume == 0.2
