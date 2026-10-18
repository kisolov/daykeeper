"""`daykeeper` entry point."""

import argparse
import asyncio
import json
import sys

from .config import load_config
from .rpc import Client, DaemonDown
from .service import ServiceError

TIMER_COMMANDS = {
    "toggle": "timer_toggle", "pause": "timer_pause", "resume": "timer_resume",
    "skip": "timer_skip", "stop": "timer_stop",
}


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="daykeeper", description="Планировщик дня с pomodoro.")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("dash", help="дашборд")
    sub.add_parser("daemon", help="запустить демон (обычно через systemd)")
    sub.add_parser("mcp", help="MCP-сервер для Claude Code (stdio)")
    sub.add_parser("waybar", help="поток статуса для модуля waybar")
    sub.add_parser("status", help="одна строка статуса waybar (JSON)")
    for name in TIMER_COMMANDS:
        sub.add_parser(name, help=f"таймер: {name}")
    add = sub.add_parser("add", help='быстро добавить задачу: "тренировка 2ч", "09:00-10:00 работа"')
    add.add_argument("text", nargs="+")
    return p


async def _status_once(client: Client) -> dict:
    stream = client.subscribe()
    try:
        return await anext(stream)
    finally:
        await stream.aclose()


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    cfg = load_config()
    client = Client(cfg.socket_path)
    try:
        match args.cmd:
            case None | "dash":
                from .tui.app import run_tui
                run_tui(client, "dash" if args.cmd == "dash" else "today")
            case "daemon":
                from .daemon import run_daemon
                run_daemon(cfg)
            case "mcp":
                from .mcp_server import run
                run(client)
            case "waybar":
                from .waybar import stream
                asyncio.run(stream(client))
            case "status":
                from .waybar import render
                print(json.dumps(render(asyncio.run(_status_once(client))), ensure_ascii=False))
            case "add":
                task = client.call("task_quick_add", text=" ".join(args.text))
                print(f"добавлено: {task['title']}")
            case cmd if cmd in TIMER_COMMANDS:
                client.call(TIMER_COMMANDS[cmd])
    except DaemonDown as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
    except ServiceError as e:
        print(e.message, file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        pass
