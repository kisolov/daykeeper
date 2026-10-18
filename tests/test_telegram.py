import pytest

from daykeeper.config import Config
from daykeeper.service import Service
from daykeeper.telegram import TelegramBot

CHAT = 42


@pytest.fixture
def bot(db, clock):
    svc = Service(db, Config(), clock)
    return TelegramBot("token", CHAT, svc, http=None), svc


def msg(text, chat=CHAT):
    return {"update_id": 1, "message": {"message_id": 3, "chat": {"id": chat}, "text": text}}


def cb(data, chat=CHAT):
    return {"update_id": 2, "callback_query": {"id": "q1", "data": data,
                                               "message": {"message_id": 7, "chat": {"id": chat}}}}


def answers(calls):
    return [p["text"] for m, p in calls if m == "answerCallbackQuery"]


def test_today_keyboard(bot):
    b, svc = bot
    svc.call("task_quick_add", text="зубы")
    svc.call("task_quick_add", text="тренировка 2ч")
    calls = b.handle_update(msg("/today"))
    (method, payload), = calls
    assert method == "sendMessage" and payload["chat_id"] == CHAT
    rows = payload["reply_markup"]["inline_keyboard"]
    assert [[btn["callback_data"] for btn in row] for row in rows] == [["done:1"], ["done:2", "start:2"]]
    assert rows[0][0]["text"] == "✓ зубы"


def test_today_hides_done(bot):
    b, svc = bot
    t = svc.call("task_quick_add", text="зубы")
    svc.call("task_done", task_id=t["id"])
    payload = b.handle_update(msg("/start"))[0][1]
    assert payload["reply_markup"]["inline_keyboard"] == []
    assert "всё сделано" in payload["text"]


def test_done_button(bot):
    b, svc = bot
    t = svc.call("task_quick_add", text="зубы")
    calls = b.handle_update(cb(f"done:{t['id']}"))
    assert answers(calls) == ["✓ зубы"]
    assert svc.call("day_get")["tasks"][0]["done"] is True
    assert any(m == "editMessageReplyMarkup" for m, _ in calls)


def test_done_twice(bot):
    b, svc = bot
    t = svc.call("task_quick_add", text="зубы")
    b.handle_update(cb(f"done:{t['id']}"))
    assert answers(b.handle_update(cb(f"done:{t['id']}"))) == ["уже сделано"]


def test_start_button(bot):
    b, svc = bot
    t = svc.call("task_quick_add", text="код 1ч")
    assert answers(b.handle_update(cb(f"start:{t['id']}"))) == ["▶ код — 47м"]
    assert svc.call("timer_status")["running"] is True


def test_start_check_task_error(bot):
    b, svc = bot
    t = svc.call("task_quick_add", text="зубы")
    assert answers(b.handle_update(cb(f"start:{t['id']}"))) == ["для галочки таймер не нужен"]


def test_deleted_task(bot):
    b, _ = bot
    assert answers(b.handle_update(cb("done:999"))) == ["задачи нет"]


def test_foreign_chat_ignored(bot):
    b, svc = bot
    t = svc.call("task_quick_add", text="зубы")
    assert b.handle_update(msg("/today", chat=1)) == []
    assert b.handle_update(cb(f"done:{t['id']}", chat=1)) == []
    assert svc.call("day_get")["tasks"][0]["done"] is False


def test_garbage_callback(bot):
    b, _ = bot
    assert answers(b.handle_update(cb("rm:-rf"))) == ["неизвестная кнопка"]


def test_unknown_text_ignored(bot):
    b, _ = bot
    calls = b.handle_update(msg("привет"))
    assert calls[0][0] == "sendMessage" and "/today" in calls[0][1]["text"]


def test_notification_payload(bot):
    b, _ = bot
    method, payload = b.notification("пора: код", "09:00–10:00", {"start:3": "▶ Запустить", "done:3": "✓ Сделано"})
    assert method == "sendMessage" and payload["text"] == "пора: код\n09:00–10:00"
    assert [btn["callback_data"] for btn in payload["reply_markup"]["inline_keyboard"][0]] == ["start:3", "done:3"]
