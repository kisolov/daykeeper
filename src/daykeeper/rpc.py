"""JSON-lines RPC over a unix socket, plus a push stream of live state.

Request:  {"id": 1, "method": "day_get", "params": {...}}
Response: {"id": 1, "result": ...} | {"id": 1, "error": {"code": ..., "message": ...}}
`subscribe` turns the connection into a stream of {"event": "state", "data": live_state}.
"""

import asyncio
import json
import socket
from collections.abc import AsyncIterator
from datetime import date, datetime, time
from pathlib import Path

from .service import Service, ServiceError

DOWN_MESSAGE = "демон не запущен (systemctl --user start daykeeper)"
DRAIN_TIMEOUT_S = 1.0


class DaemonDown(Exception):
    def __init__(self, message: str = DOWN_MESSAGE):
        super().__init__(message)


def _default(o):
    if isinstance(o, (date, datetime, time)):
        return o.isoformat()
    raise TypeError(f"not serializable: {type(o).__name__}")


def _dumps(obj) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, default=_default) + "\n").encode()


class RpcServer:
    def __init__(self, service: Service, path: Path):
        self.service = service
        self.path = path
        self.subscribers: set[asyncio.StreamWriter] = set()
        self._server: asyncio.Server | None = None
        service.on_change = self._schedule_publish

    async def start(self) -> None:
        self.path.unlink(missing_ok=True)
        self._server = await asyncio.start_unix_server(self._handle, path=str(self.path))
        self.path.chmod(0o600)

    async def close(self) -> None:
        for w in list(self.subscribers):
            w.close()
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        self.path.unlink(missing_ok=True)

    def _schedule_publish(self) -> None:
        try:
            asyncio.get_running_loop().create_task(self.publish())
        except RuntimeError:
            pass

    async def publish(self) -> None:
        if not self.subscribers:
            return
        line = _dumps({"event": "state", "data": self.service.live_state()})
        for w in list(self.subscribers):
            try:
                w.write(line)
                await asyncio.wait_for(w.drain(), DRAIN_TIMEOUT_S)
            except (ConnectionError, RuntimeError, TimeoutError):
                # a suspended TUI / stuck waybar must not stall the daemon's tick loop
                self.subscribers.discard(w)
                w.close()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while line := await reader.readline():
                try:
                    req = json.loads(line)
                    rid, method, params = req.get("id"), req["method"], req.get("params") or {}
                except (ValueError, KeyError, AttributeError):
                    writer.write(_dumps({"id": None, "error": {"code": "invalid", "message": "неверный запрос"}}))
                    await writer.drain()
                    continue
                if method == "subscribe":
                    self.subscribers.add(writer)
                    writer.write(_dumps({"event": "state", "data": self.service.live_state()}))
                    await writer.drain()
                    continue
                try:
                    resp = {"id": rid, "result": self.service.call(method, **params)}
                except ServiceError as e:
                    resp = {"id": rid, "error": {"code": e.code, "message": e.message}}
                except Exception as e:  # never kill the daemon over one request
                    resp = {"id": rid, "error": {"code": "internal", "message": f"внутренняя ошибка: {e}"}}
                writer.write(_dumps(resp))
                await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            self.subscribers.discard(writer)
            writer.close()


async def serve(service: Service, path: Path) -> RpcServer:
    server = RpcServer(service, path)
    await server.start()
    return server


def _unwrap(resp: dict):
    if "error" in resp:
        raise ServiceError(resp["error"]["code"], resp["error"]["message"])
    return resp.get("result")


class Client:
    def __init__(self, path: Path):
        self.path = Path(path)

    def call(self, method: str, **params):
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(10)
                s.connect(str(self.path))
                s.sendall(_dumps({"id": 1, "method": method, "params": params}))
                buf = b""
                while not buf.endswith(b"\n"):
                    chunk = s.recv(65536)
                    if not chunk:
                        raise DaemonDown()
                    buf += chunk
        except (FileNotFoundError, ConnectionRefusedError, ConnectionResetError):
            raise DaemonDown()
        return _unwrap(json.loads(buf))

    async def _open(self):
        try:
            return await asyncio.open_unix_connection(str(self.path), limit=2**22)
        except (FileNotFoundError, ConnectionRefusedError):
            raise DaemonDown()

    async def acall(self, method: str, **params):
        reader, writer = await self._open()
        try:
            writer.write(_dumps({"id": 1, "method": method, "params": params}))
            await writer.drain()
            line = await reader.readline()
            if not line:
                raise DaemonDown()
            return _unwrap(json.loads(line))
        finally:
            writer.close()

    async def subscribe(self) -> AsyncIterator[dict]:
        reader, writer = await self._open()
        try:
            writer.write(_dumps({"id": 1, "method": "subscribe"}))
            await writer.drain()
            while line := await reader.readline():
                msg = json.loads(line)
                if msg.get("event") == "state":
                    yield msg["data"]
            raise DaemonDown()
        finally:
            writer.close()
