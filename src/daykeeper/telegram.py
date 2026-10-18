"""Telegram remote: reminders, ✓ done, ▶ start. Accepts only the configured chat. Long polling."""

import asyncio
import logging

import httpx

from .service import Service, ServiceError

log = logging.getLogger("daykeeper.telegram")

ApiCall = tuple[str, dict]

HELP = "/today — список на сегодня"


class TelegramBot:
    def __init__(self, token: str, chat_id: int, service: Service, http: httpx.AsyncClient | None):
        self.token = token
        self.chat_id = chat_id
        self.service = service
        self.http = http
        self.offset = 0

    # --- pure part -------------------------------------------------------

    def _keyboard(self) -> list[list[dict]]:
        rows = []
        for t in self.service.call("day_get")["tasks"]:
            if t["done"]:
                continue
            row = [{"text": f"✓ {t['title']}", "callback_data": f"done:{t['id']}"}]
            if t["kind"] != "check":
                row.append({"text": "▶", "callback_data": f"start:{t['id']}"})
            rows.append(row)
        return rows

    def _today(self) -> ApiCall:
        day = self.service.call("day_get")
        rows = self._keyboard()
        text = f"Сегодня · {day['done']}/{day['total']}" + ("" if rows else " · всё сделано")
        return "sendMessage", {"chat_id": self.chat_id, "text": text, "reply_markup": {"inline_keyboard": rows}}

    def _callback(self, query: dict) -> list[ApiCall]:
        verb, _, raw = (query.get("data") or "").partition(":")
        method = {"done": "task_done", "start": "timer_start"}.get(verb)
        if method is None or not raw.isdigit():
            return [("answerCallbackQuery", {"callback_query_id": query["id"], "text": "неизвестная кнопка"})]
        try:
            result = self.service.call(method, task_id=int(raw))
        except ServiceError as e:
            return [("answerCallbackQuery", {"callback_query_id": query["id"], "text": e.message})]
        if method == "task_done":
            text = f"✓ {result['title']}"
        else:
            text = f"▶ {result['title']} — {result['remaining_s'] // 60}м"
        calls: list[ApiCall] = [("answerCallbackQuery", {"callback_query_id": query["id"], "text": text})]
        message = query.get("message")
        if message:
            calls.append(("editMessageReplyMarkup", {
                "chat_id": self.chat_id, "message_id": message["message_id"],
                "reply_markup": {"inline_keyboard": self._keyboard()},
            }))
        return calls

    def handle_update(self, update: dict) -> list[ApiCall]:
        if query := update.get("callback_query"):
            chat = (query.get("message") or {}).get("chat", {}).get("id")
            if chat != self.chat_id:
                return []
            return self._callback(query)
        message = update.get("message") or {}
        if message.get("chat", {}).get("id") != self.chat_id:
            return []
        text = (message.get("text") or "").strip()
        if text.split("@")[0] in ("/today", "/start"):
            return [self._today()]
        return [("sendMessage", {"chat_id": self.chat_id, "text": HELP})]

    def notification(self, title: str, body: str, actions: dict[str, str]) -> ApiCall:
        payload = {"chat_id": self.chat_id, "text": f"{title}\n{body}" if body else title}
        if actions:
            payload["reply_markup"] = {"inline_keyboard": [[{"text": label, "callback_data": key} for key, label in actions.items()]]}
        return "sendMessage", payload

    # --- network part ----------------------------------------------------

    async def _api(self, method: str, payload: dict, timeout: float = 15) -> dict:
        r = await self.http.post(f"https://api.telegram.org/bot{self.token}/{method}", json=payload, timeout=timeout)
        return r.json()

    async def notify(self, title: str, body: str, actions: dict[str, str]) -> None:
        method, payload = self.notification(title, body, actions)
        await self._api(method, payload)

    async def run(self) -> None:
        while True:
            try:
                data = await self._api("getUpdates", {"offset": self.offset, "timeout": 50}, timeout=60)
                for update in data.get("result", []):
                    self.offset = update["update_id"] + 1
                    for method, payload in self.handle_update(update):
                        await self._api(method, payload)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("telegram: %s", e)
                await asyncio.sleep(5)
