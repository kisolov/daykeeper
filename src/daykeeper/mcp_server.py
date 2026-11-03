"""MCP server for Claude Code: every Service operation as a tool, plus plan_context.

Tools talk to the daemon through the RPC client; the daemon stays the only writer.
"""

import json
from datetime import date, timedelta
from typing import Literal, Protocol

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from .rpc import DaemonDown
from .service import ServiceError

INSTRUCTIONS = """daykeeper — планировщик дня пользователя с pomodoro (47 мин работы / 13 отдыха, длительность
задачи — время на часах: 1ч = 1 помидор). Ты — основной способ управлять планом: пользователь диктует задачи,
ты их создаёшь и расставляешь. Виды задач: check — галочка (сделал/не сделал), timed — со start/end ЧЧ:ММ
(в начало приходит напоминание), duration — с duration_min (запускается когда удобно). Один список дня без групп;
единственное правило порядка: задача с более поздним временем не может стоять выше задачи с более ранним.
Перед «спланируй завтра» зови plan_context. Трекеры (вес, сон, настроение) вносишь только ты — tracker_log.
Даты — ГГГГ-ММ-ДД, по умолчанию сегодня."""


class Backend(Protocol):
    def call(self, method: str, **params): ...


def _dump(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def build_server(backend: Backend) -> MCPServer:
    server = MCPServer("daykeeper", instructions=INSTRUCTIONS)

    def call(method: str, **params) -> str:
        params = {k: v for k, v in params.items() if v is not None}
        try:
            return _dump(backend.call(method, **params))
        except (ServiceError, DaemonDown) as e:
            raise ToolError(getattr(e, "message", None) or str(e))

    def tool(fn):
        server.add_tool(fn, structured_output=False)
        return fn

    # --- days & tasks ----------------------------------------------------

    @tool
    def day_get(day: str | None = None) -> str:
        """Список задач дня (по умолчанию сегодня) в порядке, со статусом, помидорами и фокусом."""
        return call("day_get", day=day)

    @tool
    def task_add(title: str, kind: Literal["check", "timed", "duration"], day: str | None = None,
                 start: str | None = None, end: str | None = None, duration_min: int | None = None,
                 tag: str | None = None, index: int | None = None) -> str:
        """Добавить задачу. kind: check — галочка; timed — нужны start и end (ЧЧ:ММ); duration — нужен duration_min.
        tag — метка/проект, по ней считаются цели. index — позиция в списке (0 — сверху); без index задача со
        временем встаёт по времени, остальные — в конец. Время позже не может стоять выше раньше."""
        return call("task_add", title=title, kind=kind, day=day, start=start, end=end,
                    duration_min=duration_min, tag=tag, index=index)

    @tool
    def task_quick_add(text: str, day: str | None = None) -> str:
        """Добавить задачу одной строкой: «зубы», «тренировка 2ч», «учёба 90м», «09:00-10:00 работа»."""
        return call("task_quick_add", text=text, day=day)

    @tool
    def task_update(task_id: int, title: str | None = None, kind: Literal["check", "timed", "duration"] | None = None,
                    day: str | None = None, start: str | None = None, end: str | None = None,
                    duration_min: int | None = None, tag: str | None = None) -> str:
        """Изменить задачу (название, вид, день — перенос, время, длительность, метку). Смена времени сама
        переставляет задачу на ближайшее допустимое место."""
        fields = {k: v for k, v in dict(title=title, kind=kind, day=day, start=start, end=end,
                                        duration_min=duration_min, tag=tag).items() if v is not None}
        return call("task_update", task_id=task_id, **fields)

    @tool
    def task_delete(task_id: int) -> str:
        """Удалить задачу."""
        return call("task_delete", task_id=task_id)

    @tool
    def task_move(task_id: int, index: int) -> str:
        """Переставить задачу на позицию index (0 — сверху). Ошибка, если нарушится порядок по времени."""
        return call("task_move", task_id=task_id, index=index)

    @tool
    def task_done(task_id: int, done: bool = True) -> str:
        """Отметить задачу сделанной (done=false — снять отметку). Задним числом тоже можно."""
        return call("task_done", task_id=task_id, done=done)

    # --- timer -----------------------------------------------------------

    @tool
    def timer_start(task_id: int) -> str:
        """Запустить таймер задачи (не для галочек). Продолжает с места остановки; другой таймер останавливается."""
        return call("timer_start", task_id=task_id)

    @tool
    def timer_pause() -> str:
        """Пауза таймера."""
        return call("timer_pause")

    @tool
    def timer_resume() -> str:
        """Продолжить таймер после паузы."""
        return call("timer_resume")

    @tool
    def timer_toggle() -> str:
        """Пауза/продолжить."""
        return call("timer_toggle")

    @tool
    def timer_skip() -> str:
        """Пропустить текущую фазу (работа → отдых, отдых → работа)."""
        return call("timer_skip")

    @tool
    def timer_stop() -> str:
        """Остановить таймер; отработанное засчитывается, следующий запуск продолжит с того же места."""
        return call("timer_stop")

    @tool
    def timer_status() -> str:
        """Что сейчас идёт: задача, фаза, «помидор N из M», сколько осталось."""
        return call("timer_status")

    # --- day lifecycle ---------------------------------------------------

    @tool
    def day_close(day: str | None = None) -> str:
        """«Завершить день»: сохранить и вернуть сводку."""
        return call("day_close", day=day)

    @tool
    def day_summary(day: str | None = None) -> str:
        """Сводка дня: сделано/не сделано, фокус, помидоры, привычки, цели, мотивация."""
        return call("day_summary", day=day)

    @tool
    def summary_pending() -> str:
        """Сводка автоматически закрытого дня, которую пользователь ещё не видел (или null)."""
        return call("summary_pending")

    @tool
    def summary_seen(day: str) -> str:
        """Отметить сводку дня (и более ранних) просмотренной."""
        return call("summary_seen", day=day)

    # --- habits ----------------------------------------------------------

    @tool
    def habit_add(title: str, weekdays: list[int] | None = None, tag: str | None = None) -> str:
        """Привычка — галочка, которая сама появляется в списке в дни weekdays (0 пн … 6 вс; по умолчанию каждый день)."""
        return call("habit_add", title=title, weekdays=weekdays, tag=tag)

    @tool
    def habit_update(habit_id: int, title: str | None = None, weekdays: list[int] | None = None,
                     tag: str | None = None, active: bool | None = None) -> str:
        """Изменить привычку; active=false — выключить."""
        fields = {k: v for k, v in dict(title=title, weekdays=weekdays, tag=tag, active=active).items() if v is not None}
        return call("habit_update", habit_id=habit_id, **fields)

    @tool
    def habit_delete(habit_id: int) -> str:
        """Удалить привычку."""
        return call("habit_delete", habit_id=habit_id)

    @tool
    def habit_list() -> str:
        """Привычки с текущей и лучшей серией."""
        return call("habit_list")

    # --- goals -----------------------------------------------------------

    @tool
    def goal_add(title: str, kind: Literal["focus_tag", "tracker", "count_tag"], target: float,
                 tag: str | None = None, tracker: str | None = None, period: Literal["week"] | None = None,
                 deadline: str | None = None) -> str:
        """Цель. focus_tag — часы фокуса по задачам с tag; count_tag — число сделанных задач с tag;
        tracker — значение трекера (по имени). period=week — каждую неделю; deadline — к дате."""
        return call("goal_add", title=title, kind=kind, target=target, tag=tag, tracker=tracker,
                    period=period, deadline=deadline)

    @tool
    def goal_update(goal_id: int, title: str | None = None, target: float | None = None,
                    deadline: str | None = None) -> str:
        """Изменить цель."""
        fields = {k: v for k, v in dict(title=title, target=target, deadline=deadline).items() if v is not None}
        return call("goal_update", goal_id=goal_id, **fields)

    @tool
    def goal_delete(goal_id: int) -> str:
        """Удалить цель."""
        return call("goal_delete", goal_id=goal_id)

    @tool
    def goal_list() -> str:
        """Цели с прогрессом, ожидаемым темпом и отставанием (behind)."""
        return call("goal_list")

    # --- trackers --------------------------------------------------------

    @tool
    def tracker_add(name: str, unit: str | None = None) -> str:
        """Новый трекер — число раз в день (вес, сон, настроение)."""
        return call("tracker_add", name=name, unit=unit)

    @tool
    def tracker_delete(tracker_id: int) -> str:
        """Удалить трекер со всеми значениями."""
        return call("tracker_delete", tracker_id=tracker_id)

    @tool
    def tracker_list() -> str:
        """Трекеры с последним значением и рядом за 7 дней."""
        return call("tracker_list")

    @tool
    def tracker_log(tracker: str, value: float, day: str | None = None) -> str:
        """Записать значение трекера (по имени) за день; повтор в тот же день перезаписывает."""
        return call("tracker_log", tracker=tracker, value=value, day=day)

    # --- stats -----------------------------------------------------------

    @tool
    def stats_range(start: str, end: str) -> str:
        """Секунды фокуса по дням за период."""
        return call("stats_range", start=start, end=end)

    @tool
    def dashboard() -> str:
        """Всё с экрана дашборда: сегодня, неделя, цели, привычки, трекеры, мотивация."""
        return call("dashboard")

    @tool
    def history(start: str, end: str) -> str:
        """Сводки всех дней с задачами за период."""
        return call("history", start=start, end=end)

    # --- site block ------------------------------------------------------

    @tool
    def block_status() -> str:
        """Блокировка Instagram/YouTube: включена ли, до скольких открыто, сколько разблокировок сегодня из лимита."""
        return call("block_status")

    @tool
    def block_challenge() -> str:
        """Шаг 1 разблокировки на час: выдать случайный код. Звать, только когда пользователь сам прямо попросил
        открыть соцсети. Код показать пользователю — он может перепечатать его сам (daykeeper unlock), или
        разблокировку по его просьбе делаешь ты через block_unlock. Лимит разблокировок в день — в ответе."""
        return call("block_challenge")

    @tool
    def block_unlock(code: str) -> str:
        """Шаг 2: снять блок на час кодом из block_challenge. Через час блок вернётся сам."""
        return call("block_unlock", code=code)

    @tool
    def block_lock() -> str:
        """Вернуть блокировку сразу, не дожидаясь конца часа."""
        return call("block_lock")

    @tool
    def plan_context(days: int = 7) -> str:
        """Звать перед планированием завтра: сегодня, завтра, непросмотренная сводка, сводки за последние days дней,
        цели с отставанием, привычки с сериями."""
        try:
            today = backend.call("day_get")
            d = date.fromisoformat(today["day"])
            ctx = {
                "today": today,
                "tomorrow": backend.call("day_get", day=(d + timedelta(days=1)).isoformat()),
                "pending_summary": backend.call("summary_pending"),
                "recent": backend.call("history", start=(d - timedelta(days=days)).isoformat(),
                                       end=(d - timedelta(days=1)).isoformat()),
                "goals": backend.call("goal_list"),
                "habits": backend.call("habit_list"),
            }
        except (ServiceError, DaemonDown) as e:
            raise ToolError(getattr(e, "message", None) or str(e))
        return _dump(ctx)

    return server


def run(backend: Backend) -> None:
    build_server(backend).run("stdio")
