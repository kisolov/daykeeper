# daykeeper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Личный планировщик дня с pomodoro: TUI из waybar/терминала, демон с таймером и напоминаниями, Telegram-пульт, MCP-сервер, через который Claude Code ведёт планирование.

**Architecture:** Один Python-пакет. Чистая логика (деление на помидоры, правило порядка, статистика) — отдельные модули без I/O. `Service` над SQLite — единственная точка изменения данных; им владеет демон (`systemd --user`), который также крутит таймер, напоминания и Telegram-бота. TUI, MCP, CLI и waybar — клиенты демона по JSON-lines через unix-сокет.

**Tech Stack:** Python 3.14, uv, SQLite (`sqlite3` stdlib), Textual (TUI), `mcp` (официальный Python SDK, FastMCP), httpx (Telegram Bot API, long polling), pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-10-18-daykeeper-design.md`

## Global Constraints

- Цикл pomodoro по умолчанию **47 работы / 13 отдыха**, задаётся в `~/.config/daykeeper/config.toml` (`work_min`, `break_min`).
- Длительность задачи — время на часах, включая отдых: 60м → 47+13; 120м → 47+13+47+13; 90м → 47+13+30.
- Порядок: задача с более поздним временем не может стоять выше задачи с более ранним; всё остальное двигается свободно.
- Список дня **без группировки по видам**; вид — только значок в строке (`✓`, время слева, `⏱ 2ч · 2🍅`).
- Мотивация — только факты из статистики, никаких цитат.
- От Obsidian не зависит и туда не пишет.
- Telegram: только напоминания, «✓ сделано», «▶ запустить»; команды принимаются только из `telegram.chat_id` в конфиге; long polling.
- Трекеры вносятся только через Claude (MCP).
- Данные: `~/.local/share/daykeeper/daykeeper.db`; сокет: `$XDG_RUNTIME_DIR/daykeeper.sock`; токен бота — только в конфиге или `DAYKEEPER_TG_TOKEN`, не в репозитории.
- Цвета Lumon: accent `#6fb8e3`, accent-bright `#f2fcff`, muted `#4A6B80`, фон `#0f1a24`; первая буква слова акцентом, как в модулях waybar.
- «День» = локальная календарная дата; фокус, идущий через полночь, относится к дню задачи.
- Все тексты интерфейса — на русском.

## Review Focus

1. **Демон не запущен** — TUI, `daykeeper toggle` и waybar не падают с трейсбеком: TUI показывает «демон не запущен (systemctl --user start daykeeper)», waybar выводит idle-строку и переподключается. → тесты в Task 8 и Task 11.
2. **Демон перезапустили посреди помидора** — таймер восстанавливается из БД на паузе с тем же оставшимся временем, отработанное не теряется. → тест в Task 6.
3. **Двойной старт / старт другой задачи при идущем таймере** — текущий останавливается с записью отрезка, новый стартует; таймер никогда не «двоится». → тест в Task 6.
4. **Мусор в быстром вводе и в MCP-параметрах** (`25:00`, `10:00-09:00`, пустой заголовок, `0м`) — понятная ошибка на русском, без записи в БД. → тесты в Task 4 и Task 12.
5. **Чужой чат или повтор нажатия кнопки в Telegram** (нажал «✓» на уже сделанной задаче, задача удалена) — чужому молчание, своему — короткий ответ «уже сделано»/«задачи нет», без исключения в цикле бота. → тест в Task 10.

---

## File Structure

```
pyproject.toml                    # пакет, зависимости, entry point `daykeeper`
src/daykeeper/
  config.py       # пути, загрузка config.toml → Config
  models.py       # dataclass-ы: Task, Phase, Habit, Goal, Tracker, Segment, TimerState, *View
  db.py           # соединение, схема, миграции (user_version)
  pomodoro.py     # split_phases — чисто
  ordering.py     # правило порядка — чисто
  quickadd.py     # разбор строки быстрого ввода — чисто
  repo.py         # SQL CRUD
  days.py         # жизненный цикл дня: привычки в список, автозакрытие, снимок сводки
  timer.py        # машина состояний таймера
  stats.py        # фокус, серии, цели, сводка, мотивация
  service.py      # фасад: все операции, валидация, события
  rpc.py          # JSON-lines сервер/клиент на unix-сокете, подписка
  notify.py       # notify-send
  scheduler.py    # какие напоминания пора слать
  telegram.py     # бот
  daemon.py       # asyncio: rpc + тик + напоминания + бот
  mcp_server.py   # инструменты для Claude Code
  waybar.py       # формат статуса и потоковый режим
  cli.py          # entry point
  tui/app.py, tui/today.py, tui/summary.py, tui/dashboard.py, tui/widgets.py, tui/lumon.tcss
contrib/daykeeper.service
tests/...
```

## Shared Interfaces (заданы в Task 1–3, используются везде)

```python
# models.py
Kind = Literal["check", "timed", "duration"]

@dataclass
class Task:
    id: int; day: date; title: str; kind: Kind; position: int
    start: time | None = None; end: time | None = None       # только timed
    duration_min: int | None = None                           # только duration
    tag: str | None = None; habit_id: int | None = None
    done: bool = False; done_at: datetime | None = None
    progress_phase: int = 0; progress_elapsed_s: int = 0      # для продолжения таймера
    @property
    def planned_min(self) -> int | None: ...  # timed: end-start в минутах; duration: duration_min; check: None

@dataclass
class Phase: kind: Literal["work", "break"]; minutes: int

@dataclass
class Segment: task_id: int; day: date; started: datetime; ended: datetime; seconds: int; completed: bool
# completed=True только у отрезка, закрывшего полную рабочую фазу (= один 🍅)

@dataclass
class TimerState:
    task_id: int; phases: list[Phase]; phase_index: int
    phase_elapsed_s: int; running: bool; resumed_at: datetime | None
```

Даты/время в БД — ISO-строки в локальном времени. `Clock = Callable[[], datetime]` передаётся во всё, где нужно «сейчас» (тесты подставляют фиктивные часы).

---

### Task 1: Каркас, конфиг, схема БД, модели

**Files:**
- Create: `pyproject.toml`, `src/daykeeper/__init__.py`, `config.py`, `models.py`, `db.py`, `.gitignore`
- Test: `tests/test_db.py`, `tests/test_config.py`, `tests/conftest.py`

**Interfaces:**
- Produces: `Config(work_min=47, break_min=13, db_path: Path, socket_path: Path, tg_token: str|None, tg_chat_id: int|None)`; `load_config(path: Path | None = None) -> Config` (нет файла → дефолты; `DAYKEEPER_TG_TOKEN` перекрывает токен; `DAYKEEPER_DB`/`DAYKEEPER_SOCKET` перекрывают пути — для тестов); `connect(path: Path) -> sqlite3.Connection` (создаёт папку, `foreign_keys=ON`, `row_factory=Row`, применяет схему); все dataclass-ы из Shared Interfaces + `Habit(id, title, weekdays: frozenset[int], tag, active)`, `Tracker(id, name, unit)`, `Goal(id, title, kind: Literal["focus_tag","tracker","count_tag"], target: float, tag: str|None, tracker_id: int|None, period: Literal["week"]|None, deadline: date|None, created: date)`.
- Таблицы: `tasks`, `habits`, `trackers`, `tracker_entries(tracker_id, day, value, UNIQUE(tracker_id, day))`, `goals`, `segments`, `days(day PK, spawned INT, closed INT, summary_json TEXT, summary_seen INT)`, `timer(id=1 CHECK, task_id, phases_json, phase_index, phase_elapsed_s, running, resumed_at)`.
- `conftest.py`: фикстуры `db` (временная БД в `tmp_path`) и `clock` (`FakeClock` с `.now` и `.advance(seconds)`).

- [ ] **Step 1:** `uv init --package --name daykeeper`, `uv add textual mcp httpx`, `uv add --dev pytest pytest-asyncio`; `.gitignore`: `.venv/`, `__pycache__/`, `.superpowers/`. Записать в `pyproject.toml` фактически поставленные версии (`>=` текущей).
- [ ] **Step 2: Failing tests**
```python
def test_connect_creates_schema(tmp_path):
    con = connect(tmp_path / "a" / "x.db")
    names = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
    assert {"tasks","habits","trackers","tracker_entries","goals","segments","days","timer"} <= names
    assert con.execute("pragma user_version").fetchone()[0] == 1

def test_config_defaults(tmp_path):
    c = load_config(tmp_path / "none.toml")
    assert (c.work_min, c.break_min) == (47, 13) and c.tg_token is None

def test_config_env_token(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYKEEPER_TG_TOKEN", "t")
    assert load_config(tmp_path / "none.toml").tg_token == "t"

def test_planned_min():
    assert Task(1, date(2026,10,18), "w", "timed", 0, start=time(9), end=time(10,30)).planned_min == 90
    assert Task(1, date(2026,10,18), "w", "duration", 0, duration_min=120).planned_min == 120
    assert Task(1, date(2026,10,18), "w", "check", 0).planned_min is None
```
- [ ] **Step 3:** `uv run pytest -q` → FAIL (import errors).
- [ ] **Step 4:** Реализовать.
- [ ] **Step 5:** `uv run pytest -q` → PASS.
- [ ] **Step 6:** `git add -A && git commit -m "feat: scaffold, config, schema, models"`

---

### Task 2: Деление на помидоры

**Files:** Create `src/daykeeper/pomodoro.py`; Test `tests/test_pomodoro.py`

**Interfaces:**
- Produces: `split_phases(total_min: int, work_min: int = 47, break_min: int = 13) -> list[Phase]` (`total_min <= 0` → `ValueError`); `work_minutes(phases) -> int`; `pomodoro_count(total_min, work_min=47, break_min=13) -> int` (число рабочих фаз).

- [ ] **Step 1: Failing tests**
```python
W, B = "work", "break"
@pytest.mark.parametrize("total,expected", [
    (60,  [(W,47),(B,13)]),
    (120, [(W,47),(B,13),(W,47),(B,13)]),
    (90,  [(W,47),(B,13),(W,30)]),
    (30,  [(W,30)]),
    (50,  [(W,47),(B,3)]),
])
def test_split(total, expected):
    assert [(p.kind, p.minutes) for p in split_phases(total)] == expected

def test_split_custom(): assert [(p.kind,p.minutes) for p in split_phases(60, 25, 5)] == [(W,25),(B,5),(W,25),(B,5)]
def test_split_zero(): pytest.raises(ValueError, split_phases, 0)
def test_count(): assert pomodoro_count(120) == 2 and pomodoro_count(60) == 1 and pomodoro_count(90) == 2
```
- [ ] **Step 2:** `uv run pytest tests/test_pomodoro.py -q` → FAIL.
- [ ] **Step 3:** Реализовать: пока остаток > 0 — работа `min(остаток, work)`, затем отдых `min(остаток, break)` если > 0.
- [ ] **Step 4:** → PASS. **Step 5:** commit `feat: pomodoro split`.

---

### Task 3: Правило порядка

**Files:** Create `src/daykeeper/ordering.py`; Test `tests/test_ordering.py`

**Interfaces:**
- Produces: `class OrderError(ValueError)`; все функции принимают список задач **в текущем порядке** и возвращают новый список в новом порядке (позиции переписывает вызывающий как 0..n-1):
  - `is_valid(tasks) -> bool` — `start` у timed-задач не убывает по порядку.
  - `insert_index(tasks, new: Task) -> int` — timed: сразу после последней timed с `start <= new.start`, если таких нет — перед первой timed (или 0); остальные — `len(tasks)`.
  - `move(tasks, task_id, index) -> list[Task]` — `OrderError("задача 19:00 не может стоять выше 09:00")` если нарушено.
  - `settle(tasks, task_id) -> list[Task]` — после смены времени: если порядок нарушен, переставить задачу на ближайший к её текущему индексу допустимый индекс (при равенстве — выше).

- [ ] **Step 1: Failing tests** (пример из спеки: работа 9–10, зубы, тренировка 2ч, чтение, работа 19–20)
```python
def day(): return [t(1,"timed","09:00","10:00"), t(2,"check"), t(3,"duration",dur=120), t(4,"check"), t(5,"timed","19:00","20:00")]
def ids(ts): return [x.id for x in ts]

def test_free_task_moves_anywhere(): assert ids(move(day(), 2, 4)) == [1,3,4,2,5]
def test_free_task_above_first_timed(): assert ids(move(day(), 4, 0)) == [4,1,2,3,5]
def test_timed_moves_among_free(): assert ids(move(day(), 5, 2)) == [1,2,5,3,4]
def test_timed_cannot_pass_earlier(): pytest.raises(OrderError, move, day(), 5, 0)
def test_insert_timed(): assert insert_index(day(), t(9,"timed","15:00","16:00")) == 4
def test_insert_timed_earliest(): assert insert_index(day(), t(9,"timed","07:00","08:00")) == 0
def test_insert_free(): assert insert_index(day(), t(9,"check")) == 5
def test_settle_after_time_change():
    ts = day(); ts[4].start = time(8)          # 19:00 → 08:00
    assert ids(settle(ts, 5)) == [5,1,2,3,4]
```
(`t(...)` — хелпер в тесте, строит `Task`.)
- [ ] **Step 2:** → FAIL. **Step 3:** Реализовать. **Step 4:** → PASS. **Step 5:** commit `feat: ordering rule`.

---

### Task 4: Быстрый ввод и репозиторий задач

**Files:** Create `quickadd.py`, `repo.py`; Test `tests/test_quickadd.py`, `tests/test_repo.py`

**Interfaces:**
- Consumes: `connect`, модели, `ordering`.
- Produces:
  - `parse_quick_add(text: str) -> dict` → ключи `title, kind, start, end, duration_min`; `ValueError` с русским текстом.
  - `class Repo(con)`: `tasks(day) -> list[Task]` (по `position`); `task(id) -> Task` (`KeyError`); `insert_task(task: Task, index: int | None) -> Task` (индекс по `ordering.insert_index`, если None; переписывает позиции); `update_task(id, **fields) -> Task` (смена `start/end` → `ordering.settle`); `delete_task(id)`; `move_task(id, index) -> list[Task]`; `set_done(id, done: bool, at: datetime)`; `save_progress(id, phase, elapsed_s)`; аналогичные CRUD для `habits`, `trackers` (+ `log_tracker(tracker_id, day, value)` — upsert), `goals`; `add_segment(seg)`, `segments(start: date, end: date) -> list[Segment]`; `day_row(day) -> dict|None`, `upsert_day(day, **fields)`; `load_timer() -> TimerState|None`, `save_timer(state|None)`.
  - Валидация в `insert_task/update_task`: пустой заголовок; timed без `start/end` или `end <= start`; duration без `duration_min > 0` → `ValueError` (русский текст).

- [ ] **Step 1: Failing tests**
```python
def test_qa_check():    assert parse_quick_add("почистить зубы") == {"title":"почистить зубы","kind":"check","start":None,"end":None,"duration_min":None}
def test_qa_timed():    r = parse_quick_add("09:00-10:00 работа"); assert (r["kind"], r["start"], r["end"], r["title"]) == ("timed", time(9), time(10), "работа")
def test_qa_hours():    assert parse_quick_add("тренировка 2ч")["duration_min"] == 120
def test_qa_minutes():  assert parse_quick_add("учёба 90м")["duration_min"] == 90
def test_qa_mixed():    assert parse_quick_add("код 1ч30м")["duration_min"] == 90
@pytest.mark.parametrize("bad", ["", "   ", "25:00-26:00 x", "10:00-09:00 x", "x 0м"])
def test_qa_bad(bad):   pytest.raises(ValueError, parse_quick_add, bad)

def test_insert_respects_order(db):
    r = Repo(db); d = date(2026,10,18)
    r.insert_task(T(d,"работа","timed",start=time(19),end=time(20)), None)
    r.insert_task(T(d,"утро","timed",start=time(9),end=time(10)), None)
    r.insert_task(T(d,"зубы","check"), None)
    assert [x.title for x in r.tasks(d)] == ["утро","работа","зубы"]
def test_move_invalid_keeps_db(db): ...  # move_task нарушает → OrderError, порядок в БД прежний
def test_update_time_settles(db): ...    # 19:00 → 08:00 поднимает задачу наверх
def test_tracker_log_upsert(db): ...     # два log в один день → одно значение, последнее
def test_timer_roundtrip(db): ...        # save_timer → load_timer равны; save_timer(None) → None
```
- [ ] **Step 2:** → FAIL. **Step 3:** Реализовать (быстрый ввод: время `HH:MM-HH:MM` в начале строки; длительность `(\d+ч)?(\d+м)?` в конце). **Step 4:** → PASS. **Step 5:** commit `feat: quick add and repository`.

---

### Task 5: Жизненный цикл дня

**Files:** Create `days.py`; Test `tests/test_days.py`

**Interfaces:**
- Consumes: `Repo`, `stats.day_summary` (Task 7 — до него использовать заглушку не нужно: делать Task 5 после Task 7 **или** передавать `summarize: Callable[[date], dict]` параметром; выбрано второе).
- Produces: `class Days(repo, summarize: Callable[[date], dict], clock)`:
  - `ensure(day: date) -> None` — если `spawned=0`: для каждой активной привычки, у которой `day.weekday() in weekdays`, вставить check-задачу (`habit_id`, `tag` привычки) в конец; `spawned=1`. Затем закрыть все дни `< day` с `closed=0`, у которых есть задачи: `summary_json=summarize(d)`, `closed=1`, `summary_seen=0`.
  - `close(day) -> dict` — снимок, `closed=1`, `summary_seen=1` (пользователь видит сводку сейчас).
  - `pending_summary() -> tuple[date, dict] | None` — самый поздний закрытый день с `summary_seen=0`; `mark_seen(day)`.

- [ ] **Step 1: Failing tests**
```python
def test_habits_spawn_once(db, clock): ...      # пн-пт привычка; ensure(вс) — нет задачи; ensure(пн) дважды — одна задача
def test_autoclose_previous(db, clock): ...     # задача на 17-е, ensure(18-е) → day_row(17).closed==1, pending_summary()[0]==17-е
def test_close_marks_seen(db, clock): ...       # close(18) → pending_summary() is None
def test_closed_day_still_editable(db, clock):  # после close set_done по задаче дня проходит
```
- [ ] **Step 2–5:** FAIL → реализовать → PASS → commit `feat: day lifecycle`.

---

### Task 6: Таймер

**Files:** Create `timer.py`; Test `tests/test_timer.py`

**Interfaces:**
- Consumes: `Repo`, `split_phases`, `Config`.
- Produces: события `PhaseEnded(task_id, phase: Phase, next: Phase | None)`, `TaskCompleted(task_id)`; `class TimerError(ValueError)`;
  `class Timer(repo, cfg, clock)`, состояние хранится в `repo.save_timer` при каждом изменении:
  - `state -> TimerState | None`; `remaining_s() -> int`
  - `start(task_id) -> list[Event]` — check-задача или сделанная → `TimerError`; идёт другой таймер → сначала `stop()`. Фазы = `split_phases(task.planned_min, cfg.work_min, cfg.break_min)`, позиция = `task.progress_phase/progress_elapsed_s`.
  - `pause()`, `resume()`, `toggle()`, `skip() -> list[Event]`, `stop()`, `tick() -> list[Event]` (вызывается раз в секунду; закрывает истёкшие фазы, может закрыть несколько подряд, если часы прыгнули).
  - `restore()` — при старте демона: загрузить из БД; если было `running`, учесть время до `resumed_at`→«сейчас» не дольше конца текущей фазы, записать отрезок и поставить на **паузу**.
  - Отрезок (`Segment`) пишется при паузе/стопе/пропуске/конце рабочей фазы; `day = task.day`; `completed=True` только при полной рабочей фазе. После каждого изменения — `repo.save_progress`.
  - Конец последней рабочей фазы → `set_done` + `TaskCompleted`; хвостовой отдых доигрывается, затем `state=None`.

- [ ] **Step 1: Failing tests**
```python
def test_full_pomodoro(...):     # duration 60: start, advance 47*60, tick → PhaseEnded(work, next=break), 1 segment completed, 2820 s
def test_partial_counts(...):    # start, advance 40*60, stop → segment 2400 s, completed False; task.progress == (0, 2400)
def test_resume_continues(...):  # после stop: start снова → phase_index 0, remaining 7*60
def test_skip_work(...):         # skip на 10-й минуте → отрезок 600 s, фаза = break
def test_autodone(...):          # duration 60: 47 мин → TaskCompleted, task.done; ещё 13 мин → state is None
def test_single_timer(...):      # start(A), 5 мин, start(B) → отрезок A 300 s, state.task_id == B
def test_check_task_rejected(...): pytest.raises(TimerError, ...)
def test_restore_after_crash(...): # start, advance 10 мин, новый Timer(...).restore() → running False, отрезок 600 s, remaining 37*60
def test_midnight_day(...):      # задача 18-го, старт 23:50, стоп 00:20 → segment.day == 18-е
def test_clock_jump(...):        # advance 2ч одним прыжком на задаче 2ч → все фазы закрыты, TaskCompleted
```
- [ ] **Step 2–5:** FAIL → реализовать → PASS → commit `feat: timer state machine`.

---

### Task 7: Статистика, цели, сводка, мотивация

**Files:** Create `stats.py`; Test `tests/test_stats.py`

**Interfaces:**
- Consumes: `Repo`.
- Produces: `class Stats(repo)`:
  - `focus_by_day(start, end) -> dict[date, int]` (секунды; все отрезки); `pomodoros(day) -> int` (отрезки `completed`)
  - `habit_grid(habit_id, end, days=14) -> list[bool | None]` (None — день не по расписанию; старые→новые)
  - `habit_streak(habit_id, today) -> tuple[int, int]` (текущая, лучшая): дни по расписанию подряд с отметкой; невыполненная сегодня **не рвёт** серию.
  - `goal_progress(goal, today) -> dict` → `value, target, expected, delta` (`focus_tag`: часы отрезков задач с тегом за период/до дедлайна; `count_tag`: число сделанных задач с тегом; `tracker`: последнее значение, `start` = первое значение после `created`). `expected`: `week` — `target * (today.weekday()+1)/7`; дедлайн — линейно от `created` до `deadline`.
  - `day_summary(day) -> dict` → `done: [title], not_done: [title], focus_s, pomodoros, habits: [{title, done, streak}], goals: [goal_progress...], motivation: str|None`
  - `motivation(today) -> str | None` — первый сработавший факт по приоритету: (1) неделя — лучшая по фокусу за последние 4 недели («лучшая неделя по фокусу за месяц»); (2) серия привычки ≥ 3 и близко к рекорду или рекорд («зарядка — 10 дней подряд, рекорд 14» / «… — новый рекорд»); (3) сегодня фокуса больше, чем вчера («сегодня на 40м больше фокуса, чем вчера»). Нет фактов → None.
  - `dashboard(today) -> dict` — всё для экрана дашборда: `today` (done/total/focus_s/pomodoros/next_timed), `week` (`focus_by_day` пн–вс + итог прошлой недели), `goals`, `habits` (grid+streak), `trackers` (последнее значение + 7 значений), `motivation`.

- [ ] **Step 1: Failing tests** — по одному на: фокус с прерванным отрезком; серию с пропуском и «сегодня не рвёт»; сетку с днями не по расписанию; `focus_tag` за неделю и `delta` в среду (target 20ч, факт 7ч → expected 8.57ч); `tracker` к дедлайну; все три ветки мотивации и `None` на пустой БД; `day_summary` ключи и значения на примере дня.
- [ ] **Step 2–5:** FAIL → реализовать → PASS → commit `feat: stats, goals, motivation`.

---

### Task 8: Service и RPC

**Files:** Create `service.py`, `rpc.py`; Test `tests/test_service.py`, `tests/test_rpc.py`

**Interfaces:**
- Consumes: всё выше.
- Produces:
  - `class Service(con, cfg, clock)` собирает `Repo, Days, Timer, Stats`; методы принимают/возвращают JSON-совместимые значения (даты ISO-строками, `day=None` → сегодня, каждый вызов сначала делает `days.ensure(today)`). Регистр `Service.METHODS: dict[str, Callable]` — имена ниже — единственный список, который используют RPC, MCP, CLI, TUI и бот:
    `day_get(day=None)`, `task_add(title, kind, day=None, start=None, end=None, duration_min=None, tag=None, index=None)`, `task_quick_add(text, day=None)`, `task_update(task_id, **fields)`, `task_delete(task_id)`, `task_move(task_id, index)`, `task_done(task_id, done=True)`,
    `timer_start(task_id)`, `timer_pause()`, `timer_resume()`, `timer_toggle()`, `timer_skip()`, `timer_stop()`, `timer_status()`,
    `day_close(day=None)`, `day_summary(day=None)`, `summary_pending()`, `summary_seen(day)`,
    `habit_add(title, weekdays, tag=None)`, `habit_update(habit_id, **f)`, `habit_delete(habit_id)`, `habit_list()`,
    `goal_add(title, kind, target, tag=None, tracker=None, period=None, deadline=None)`, `goal_update`, `goal_delete`, `goal_list()` (с прогрессом),
    `tracker_add(name, unit=None)`, `tracker_delete`, `tracker_list()`, `tracker_log(tracker, value, day=None)`,
    `stats_range(start, end)`, `dashboard()`, `history(start, end)`.
  - `day_get` возвращает `{"day", "closed", "done", "total", "focus_s", "tasks": [{"id","title","kind","start","end","duration_min","pomodoros","tag","done","running"}]}`; `timer_status` → `None` или `{"task_id","title","phase":"work|break","phase_no","phase_total","remaining_s","phase_s","running","next":[{"kind","minutes"}]}`.
  - `Service.tick() -> list[Event]` — для демона; `Service.on_event` — колбэк.
  - `ServiceError(code, message)`; `ValueError/OrderError/TimerError/KeyError` превращаются в `ServiceError` с русским текстом.
  - `rpc.serve(service, path) -> asyncio.Server`: строка `{"id","method","params"}` → `{"id","result"}`/`{"id","error":{"code","message"}}`; метод `subscribe` → далее сервер шлёт `{"event":"state","data":{"timer":timer_status(),"day":{done,total,next_timed}}}` раз в секунду и сразу после любого изменяющего вызова.
  - `class Client(path)`: `call(method, **params)` (sync, для CLI/MCP), `async acall(...)`, `async subscribe() -> AsyncIterator[dict]`; демон недоступен → `DaemonDown` с текстом «демон не запущен (systemctl --user start daykeeper)».

- [ ] **Step 1: Failing tests**
```python
def test_methods_registry_complete(svc): assert {"day_get","task_add","timer_start","dashboard","tracker_log"} <= set(Service.METHODS)
def test_quick_add_bad_input(svc):       # "10:00-09:00 x" → ServiceError, day_get пуст
def test_day_get_shape(svc): ...         # ключи как в контракте
async def test_rpc_roundtrip(tmp_path, svc): ...   # serve, Client.acall("task_quick_add", text="зубы"), затем day_get → 1 задача
async def test_rpc_error(tmp_path, svc): ...       # task_move с нарушением → error.message содержит "не может стоять выше"
async def test_subscribe_pushes_on_change(...): ...  # subscribe, timer_start → событие с timer.running True < 1 с
def test_client_daemon_down(tmp_path): pytest.raises(DaemonDown, Client(tmp_path/"no.sock").call, "day_get")
```
- [ ] **Step 2–5:** FAIL → реализовать → PASS → commit `feat: service facade and rpc`.

---

### Task 9: Демон, напоминания, systemd

**Files:** Create `notify.py`, `scheduler.py`, `daemon.py`, `contrib/daykeeper.service`; Test `tests/test_scheduler.py`

**Interfaces:**
- Consumes: `Service`, `rpc.serve`, `Config`; бот из Task 10 подключается через `Notifier`-протокол.
- Produces:
  - `due_reminders(tasks: list[Task], since: datetime, now: datetime) -> list[Task]` — timed, не сделанные, `since < start <= now` (по дню задачи).
  - `class Notifier(Protocol)`: `async notify(title: str, body: str, actions: dict[str, str]) -> None` (actions: id → подпись).
  - `DesktopNotifier` — `notify-send -a daykeeper -A start=Запустить ...` в фоне; выбранное действие → `service` (`start` → `timer_start(task_id)`).
  - `run_daemon(cfg)` — `Service.timer.restore()`, rpc-сервер, цикл раз в секунду: `service.tick()` → события в уведомления («перерыв 13м», «снова работа: …», «готово: …»); напоминания по `due_reminders` с `since` = время прошлой проверки (при старте — «сейчас», без лавины за пропущенное). Все `Notifier` из списка (рабочий стол, Telegram если настроен).
  - `contrib/daykeeper.service`: `ExecStart=%h/.local/bin/daykeeper daemon`, `Restart=on-failure`, `WantedBy=default.target`.
- [ ] **Step 1: Failing tests** — `due_reminders`: попадает 09:00 при since 08:59:30/now 09:00:01; не попадает сделанная; не попадает 09:00 при since 09:00:00 (уже было); задача другого дня не попадает.
- [ ] **Step 2–4:** FAIL → реализовать → PASS.
- [ ] **Step 5: Ручная проверка:** `DAYKEEPER_DB=/tmp/dk.db DAYKEEPER_SOCKET=/tmp/dk.sock uv run daykeeper daemon &`, затем через `Client` добавить задачу на «сейчас + 1 мин» → через минуту приходит уведомление. Убить процесс.
- [ ] **Step 6:** commit `feat: daemon and reminders`.

---

### Task 10: Telegram-бот

**Files:** Create `telegram.py`; Test `tests/test_telegram.py`

**Interfaces:**
- Consumes: `Service`, `Notifier`.
- Produces: `class TelegramBot(token, chat_id, service, http: httpx.AsyncClient)` — реализует `Notifier` (`sendMessage` с `inline_keyboard`) и `async run()` — цикл `getUpdates?timeout=50&offset=...`.
  - `handle_update(update: dict) -> list[ApiCall]` — **чистая** функция разбора (тестируется без сети): `/today` и `/start` → список несделанных задач дня кнопками `✓ <title>` (`done:<id>`) и для timed/duration ещё `▶` (`start:<id>`); callback `done:<id>` → `task_done`, ответ «✓ <title>»; `start:<id>` → `timer_start`, ответ «▶ <title> — 47м»; чужой `chat_id` → `[]`; ошибка сервиса (задачи нет / уже сделано / таймер не для галочки) → `answerCallbackQuery` с текстом ошибки.
  - Ошибки сети — пауза 5 с и повтор, без выхода из цикла.
- [ ] **Step 1: Failing tests** — `/today` строит клавиатуру (2 кнопки для duration, 1 для check); `done:<id>` отмечает; повторный `done:<id>` → ответ «уже сделано»; чужой chat → `[]`; `start:<id>` для check → текст ошибки; удалённая задача → «задачи нет».
- [ ] **Step 2–4:** FAIL → реализовать → PASS.
- [ ] **Step 5:** В `daemon.py` поднимать бота, если в конфиге есть токен и chat_id. Commit `feat: telegram bot`.

---

### Task 11: CLI и waybar

**Files:** Create `cli.py`, `waybar.py`; Modify `pyproject.toml` (`[project.scripts] daykeeper = "daykeeper.cli:main"`); Test `tests/test_waybar.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `Client`, `DaemonDown`.
- Produces:
  - `cli.main(argv=None)`: `daykeeper` → TUI «Сегодня»; `dash` → TUI дашборд; `daemon`; `mcp`; `waybar`; `status` (одна JSON-строка waybar); `toggle|pause|resume|skip|stop`; `add "<быстрый ввод>"`. Демон недоступен → сообщение `DaemonDown` в stderr, код 1, без трейсбека.
  - `waybar.render(state: dict | None) -> dict` → `{"text","class","tooltip","alt"}`: работа — `"<span color='#6fb8e3'>f</span>ocus 31:12"`, class `["work"]`; отдых — `brk`, `["break"]`; пауза — первая буква `#4A6B80` и класс `+ "paused"`; простой — `"<span color='#6fb8e3'>n</span>ext 19:00"` если есть следующая timed, иначе `"<span color='#6fb8e3'>d</span>ay 2/6"`, класс `["idle"]`; `None` (демон лежит) — `"<span color='#4A6B80'>d</span>ay —"`, `["down"]`. Tooltip: задача, «помидор N из M», следующая фаза.
  - `waybar.stream()` — подписка, на каждое событие печатает `json.dumps(render(...))` + flush; при обрыве печатает `render(None)` и переподключается каждые 2 с.
- [ ] **Step 1: Failing tests** — `render` для работы/отдыха/паузы/простоя с next/без next/None (точные строки выше); `cli.main(["toggle"])` при недоступном сокете → `SystemExit(1)` и stderr содержит «демон не запущен».
- [ ] **Step 2–4:** FAIL → реализовать → PASS. **Step 5:** commit `feat: cli and waybar`.

---

### Task 12: MCP-сервер

**Files:** Create `mcp_server.py`; Test `tests/test_mcp.py`

**Interfaces:**
- Consumes: `Client`, `Service.METHODS` (только имена/сигнатуры).
- Produces: `build_server(client) -> FastMCP` и `run()` (stdio). Инструменты — по одному на метод сервиса, с теми же именами и параметрами, и docstring на русском, где сказано, когда его звать (например `task_add`: «добавить задачу; kind: check — галочка, timed — со start/end HH:MM, duration — с duration_min; время позже не может стоять выше раньше»). Плюс инструмент `plan_context(days=7)` — в одном ответе: сегодня, завтра, незакрытое за вчера, сводки за `days` дней, цели с отставанием, привычки с сериями — то, что Claude читает перед «спланируй завтра». Ошибки сервиса возвращаются как текст ошибки инструмента, не исключение транспорта.
- [ ] **Step 0:** Посмотреть API установленной версии `mcp` (`uv run python -c "import mcp, inspect; ..."`, документация пакета) — **не по памяти**: API FastMCP менялся между версиями.
- [ ] **Step 1: Failing tests** — список инструментов сервера покрывает `Service.METHODS` + `plan_context`; вызов `task_quick_add` через тестовый клиент SDK (in-memory сессия, если есть в версии) против `Client`-заглушки возвращает задачу; ошибка сервиса приходит как `isError`.
- [ ] **Step 2–4:** FAIL → реализовать → PASS. **Step 5:** commit `feat: mcp server`.

---

### Task 13: TUI — «Сегодня»

**Files:** Create `tui/app.py`, `tui/today.py`, `tui/widgets.py`, `tui/lumon.tcss`; Test `tests/test_tui_today.py`

**Interfaces:**
- Consumes: `Client` (через протокол `Backend` с `call/acall/subscribe` — в тестах подставляется `FakeBackend` поверх `Service` на временной БД).
- Produces: `DaykeeperApp(backend, start_screen: Literal["today","dash"]="today")`; `TodayScreen`; виджеты `TaskRow`, `TimerPanel`.
  - Вид по утверждённому макету v2: заголовок `СЕГОДНЯ · вс 18 окт` и справа `2/6 · 47м фокуса`; строки `[ ]`/`[x]`/`[▶]`; timed — `09–10` слева; справа `✓` (check) или `⏱ 2ч · 2🍅` (duration) или `1🍅` (timed); **никаких групп**. Пока идёт таймер — `TimerPanel` над списком: название, «помидор N из M · работа/отдых», крупное время, прогресс-бар, «дальше: …».
  - Клавиши: `space` отметить/снять, `enter` старт таймера, `p` пауза/продолжить, `n` пропустить, `x` стоп, `J`/`K` переставить (ошибка порядка — уведомление внизу, список не меняется), `a` быстрый ввод (строка ввода, `Enter` → `task_quick_add`), `e` завершить день → `SummaryScreen`, `[`/`]` день назад/вперёд, `d` дашборд, `q` выход. Подсказка клавиш внизу.
  - При запуске: `summary_pending()` → если есть, сначала показать сводку «вчера» (после закрытия — `summary_seen`).
  - Демон недоступен → экран с текстом `DaemonDown` и `q`.
- [ ] **Step 1: Failing tests** (Textual `App.run_test()` + `pilot`)
```python
async def test_no_groups(app_with_day): # строки идут в порядке позиций, текста "ГАЛОЧКИ"/"ПО ВРЕМЕНИ" нет
async def test_space_marks_done(...)    # space на 2-й строке → task_done вызван, строка [x]
async def test_enter_starts_timer(...)  # enter на duration → TimerPanel виден, "помидор 1 из 2"
async def test_move_violation_toast(...)# K на 19–20 через 09–10 → порядок прежний, уведомление с "не может стоять выше"
async def test_quick_add(...)           # a, "тренировка 2ч", Enter → новая строка с "⏱ 2ч · 2🍅"
async def test_pending_yesterday(...)   # summary_pending не пуст → первым открыт SummaryScreen
async def test_daemon_down(...)         # backend бросает DaemonDown → текст "демон не запущен"
```
- [ ] **Step 2–4:** FAIL → реализовать → PASS.
- [ ] **Step 5: Визуально:** `uv run daykeeper` против тестового демона — сверить с макетом v2 (цвета Lumon, выравнивание правой колонки). Commit `feat: today screen`.

---

### Task 14: TUI — сводка и дашборд

**Files:** Create `tui/summary.py`, `tui/dashboard.py`; Test `tests/test_tui_dash.py`

**Interfaces:**
- Consumes: `day_close`, `day_summary`, `dashboard`.
- Produces: `SummaryScreen(day, summary: dict)` — «сделано» / «не сделано», `47м фокуса · 1🍅`, привычки с 🔥, цели за день, строка мотивации `» …` (если есть); `DashboardScreen` по утверждённому макету: блоки СЕГОДНЯ, ФОКУС ЗА НЕДЕЛЮ (бары пн–вс, итог и сравнение с прошлой ▲/▼), ЦЕЛИ (бар + «−2ч от темпа»), ПРИВЫЧКИ (сетка 14 дней ■/□/·, 🔥N), ТРЕКЕРЫ (значение + спарклайн 7 дней), строка мотивации; `←/→` неделя, `t` сегодня, `q` назад.
- [ ] **Step 1: Failing tests** — `e` на «Сегодня» вызывает `day_close` и показывает сводку с заголовками «сделано»/«не сделано»; дашборд на пустой БД рендерится без исключений и без строки мотивации; дашборд с данными: сетка привычки длиной 14, текст «от темпа» у цели с отставанием; `←` меняет неделю в заголовке.
- [ ] **Step 2–4:** FAIL → реализовать → PASS. **Step 5:** commit `feat: summary and dashboard`.

---

### Task 15: Установка и интеграция в систему

**Files:** Create `README.md` (установка, конфиг, подключение MCP, бот); Modify (вне репозитория, с бэкапом `*.bak-<ts>`): `~/.config/waybar/config.jsonc`, `~/.config/waybar/style.css`, `~/.config/hypr/waybar.lua`

- [ ] **Step 1:** `uv tool install --editable .` → `~/.local/bin/daykeeper`; `daykeeper --help` работает.
- [ ] **Step 2:** `cp contrib/daykeeper.service ~/.config/systemd/user/ && systemctl --user daemon-reload && systemctl --user enable --now daykeeper`; `systemctl --user is-active daykeeper` → `active`.
- [ ] **Step 3:** Waybar: заменить `custom/pomodoro` на `custom/daykeeper` (`"exec": "daykeeper waybar"`, `"return-type": "json"`, без `interval`, `"on-click": "~/.local/bin/waybar-float.sh waybar-day DAYKEEPER daykeeper"`, `"on-click-right": "daykeeper toggle"`); в `style.css` переименовать селекторы `#custom-pomodoro` → `#custom-daykeeper`, добавить `.paused`/`.down` → `@muted`; в `waybar.lua` правило `waybar-float-pomodoro` → класс `^waybar-day$`. Проверить JSONC парсером; `pkill -SIGUSR2 waybar`.
- [ ] **Step 4:** MCP: `claude mcp add --scope user daykeeper -- daykeeper mcp`; `claude mcp list` показывает `daykeeper` подключённым.
- [ ] **Step 5: Живая проверка:** добавить через `daykeeper add "тест 1ч"`, клик по модулю — окно открылось у правого края; `enter` — в waybar `focus 46:5x`; правый клик — пауза (приглушено); `x`; `e` — сводка.
- [ ] **Step 6:** Telegram (если пользователь дал токен и chat_id): `/today` в боте, кнопки работают. Без токена — пропустить и сказать об этом.
- [ ] **Step 7:** commit `docs: install and integration`.
