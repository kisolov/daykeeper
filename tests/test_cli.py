import pytest

from daykeeper.cli import main


@pytest.fixture
def no_daemon(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYKEEPER_SOCKET", str(tmp_path / "none.sock"))
    monkeypatch.setenv("DAYKEEPER_DB", str(tmp_path / "x.db"))


@pytest.mark.parametrize("cmd", [["toggle"], ["add", "зубы"], ["status"]])
def test_daemon_down_is_clean(no_daemon, capsys, cmd):
    with pytest.raises(SystemExit) as e:
        main(cmd)
    assert e.value.code == 1
    assert "демон не запущен" in capsys.readouterr().err


def test_help(capsys):
    with pytest.raises(SystemExit) as e:
        main(["--help"])
    assert e.value.code == 0
    assert "daemon" in capsys.readouterr().out
