"""In-process backend for TUI tests: Service on a temp DB, same call/subscribe surface as rpc.Client."""

import asyncio

from daykeeper.rpc import DaemonDown


class FakeBackend:
    def __init__(self, svc):
        self.svc = svc
        self.calls: list[tuple[str, dict]] = []
        self._changed = asyncio.Event()
        svc.on_change = self._changed.set

    def call(self, method, **params):
        self.calls.append((method, params))
        return self.svc.call(method, **params)

    async def subscribe(self):
        while True:
            yield self.svc.live_state()
            self._changed.clear()
            await self._changed.wait()


class DownBackend:
    def call(self, method, **params):
        raise DaemonDown()

    async def subscribe(self):
        raise DaemonDown()
        yield  # pragma: no cover
