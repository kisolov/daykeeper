import pytest

from daykeeper.waybar import render

ACC, MUTED = "#6fb8e3", "#4A6B80"


def timer(phase="work", running=True, remaining=31 * 60 + 12):
    return {"task_id": 1, "title": "код", "phase": phase, "pomodoro_no": 1, "pomodoro_total": 2,
            "remaining_s": remaining, "phase_s": 47 * 60, "running": running,
            "next": [{"kind": "break", "minutes": 13}]}


def state(t=None, next_timed=None, done=2, total=6):
    return {"timer": t, "day": {"done": done, "total": total, "next_timed": next_timed}}


def test_work():
    r = render(state(timer()))
    assert r["text"] == f"<span color='{ACC}'>f</span>ocus 31:12"
    assert r["class"] == ["work"] and r["alt"] == "work"
    assert "код" in r["tooltip"] and "помидор 1 из 2" in r["tooltip"] and "дальше: отдых 13м" in r["tooltip"]


def test_break():
    r = render(state(timer("break", remaining=9 * 60 + 40)))
    assert r["text"] == f"<span color='{ACC}'>b</span>rk 09:40"
    assert r["class"] == ["break"]


def test_paused():
    r = render(state(timer(running=False)))
    assert r["text"] == f"<span color='{MUTED}'>f</span>ocus 31:12"
    assert r["class"] == ["work", "paused"] and r["alt"] == "work-paused"


def test_idle_next():
    r = render(state(next_timed={"title": "VPN-бот", "start": "19:00"}))
    assert r["text"] == f"<span color='{ACC}'>n</span>ext 19:00"
    assert r["class"] == ["idle"] and "VPN-бот" in r["tooltip"]


def test_idle_day():
    r = render(state())
    assert r["text"] == f"<span color='{ACC}'>d</span>ay 2/6"
    assert r["class"] == ["idle"]


def test_down():
    r = render(None)
    assert r["text"] == f"<span color='{MUTED}'>d</span>ay —"
    assert r["class"] == ["down"] and "демон не запущен" in r["tooltip"]


@pytest.mark.parametrize("remaining,text", [(0, "00:00"), (59, "00:59"), (47 * 60, "47:00")])
def test_clock_format(remaining, text):
    assert render(state(timer(remaining=remaining)))["text"].endswith(text)


async def test_stream_without_daemon_prints_down_once(tmp_path):
    import asyncio
    import io
    import json

    from daykeeper.rpc import Client
    from daykeeper.waybar import stream

    out = io.StringIO()
    task = asyncio.create_task(stream(Client(tmp_path / "none.sock"), out))
    await asyncio.sleep(0.2)
    task.cancel()
    lines = [json.loads(x) for x in out.getvalue().splitlines()]
    assert [x["class"] for x in lines] == [["down"]]


async def test_stream_follows_daemon(tmp_path, db, clock):
    import asyncio
    import io
    import json

    from daykeeper.config import Config
    from daykeeper.rpc import Client, serve
    from daykeeper.service import Service
    from daykeeper.waybar import stream

    svc = Service(db, Config(), clock)
    srv = await serve(svc, tmp_path / "s.sock")
    svc.call("task_quick_add", text="зубы")
    out = io.StringIO()
    task = asyncio.create_task(stream(Client(tmp_path / "s.sock"), out))
    await asyncio.sleep(0.2)
    task.cancel()
    await srv.close()
    first = json.loads(out.getvalue().splitlines()[0])
    assert first["text"].endswith("ay 0/1")


def test_unblocked_is_marked():
    r = render(state() | {"block": {"blocked": False, "until": "15:40"}})
    assert r["class"] == ["idle", "unblocked"] and "соцсети открыты до 15:40" in r["tooltip"]


def test_blocked_adds_nothing():
    assert render(state() | {"block": {"blocked": True, "until": None}}) == render(state())
