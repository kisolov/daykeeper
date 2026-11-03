# daykeeper

Личный планировщик дня с pomodoro: список дня в waybar/терминале, таймер 47/13, напоминания,
привычки, цели, трекеры, Telegram-пульт. Планирование — через Claude Code (MCP).

## Установка

```bash
uv tool install --force .                       # ~/.local/bin/daykeeper
cp contrib/daykeeper.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now daykeeper
claude mcp add --scope user daykeeper -- daykeeper mcp
```

## Команды

| Команда | Что делает |
|---|---|
| `daykeeper` | экран «Сегодня» |
| `daykeeper dash` | дашборд |
| `daykeeper add "тренировка 2ч"` | быстро добавить задачу |
| `daykeeper toggle` / `pause` / `resume` / `skip` / `stop` | таймер |
| `daykeeper waybar` | поток статуса для модуля waybar |
| `daykeeper daemon` | демон (обычно через systemd) |
| `daykeeper mcp` | MCP-сервер для Claude Code |
| `daykeeper block` / `unlock` / `lock` | блокировка соцсетей: статус / открыть на час по коду / закрыть сразу |

Клавиши на «Сегодня»: `space` отметить, `enter` таймер, `p` пауза, `n` пропустить, `x` стоп,
`J/K` переставить, `a` добавить, `[ ]` день, `e` завершить день, `d` дашборд, `q` выйти.

## Конфиг

`~/.config/daykeeper/config.toml` (всё необязательно):

```toml
work_min = 47
break_min = 13

[telegram]
token = "123:ABC"      # или переменная DAYKEEPER_TG_TOKEN
chat_id = 123456789    # бот отвечает только этому чату

[sound]
enabled = true         # тихий звук: «пора», перерыв, снова работа, задача готова
volume = 0.4           # 0..1; на свои действия (пропуск, пауза, стоп) звука нет
```

Данные — `~/.local/share/daykeeper/daykeeper.db`, сокет — `$XDG_RUNTIME_DIR/daykeeper.sock`.

## Waybar

```jsonc
"custom/daykeeper": {
    "exec": "daykeeper waybar",
    "return-type": "json",
    "on-click": "~/.local/bin/waybar-float.sh waybar-day DAYKEEPER daykeeper",
    "on-click-right": "daykeeper toggle"
}
```

CSS-классы: `work`, `break`, `paused`, `idle`, `down`; плюс `unblocked`, пока соцсети открыты.

## Блокировка соцсетей

Instagram и YouTube закрыты всегда. Открыть на час можно двумя путями:

- самому: `daykeeper unlock` — показывает случайный код из 48 символов, его надо перепечатать руками;
- через Claude: попросить открыть — он зовёт MCP `block_challenge` → `block_unlock`.

Через час блок возвращается сам; не больше 3 разблокировок в день. Код, лимит и таймер — в daykeeper
(таблица `block_unlocks`). Сеть — root-хелпер `daykeeper-netblock lock|unlock`, который переключает
rule-set с `reject` в sing-box (TUN + `sniff`, поэтому DoH браузера не помогает) и перезапускает его,
рвя открытые соединения. Демон зовёт хелпер через `sudo -n` (NOPASSWD только на него).
При загрузке система поднимается с блоком; демон при старте приводит сеть к сохранённому состоянию.

Установка сетевой части (один раз):

```bash
sudo bash contrib/netblock/install.sh
```

Список доменов — `/etc/daykeeper-netblock/blocked.json` (исходник `contrib/netblock/blocked.json`).
Настройки — в конфиге:

```toml
[block]
minutes = 60
daily_limit = 3
code_len = 48
helper = "/usr/local/bin/daykeeper-netblock"
```

## Разработка

```bash
uv run pytest -q
```
