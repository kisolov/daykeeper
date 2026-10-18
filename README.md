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

CSS-классы: `work`, `break`, `paused`, `idle`, `down`.

## Разработка

```bash
uv run pytest -q
```
