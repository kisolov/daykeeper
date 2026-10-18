import json

import pytest
from mcp import Client as McpClient

from daykeeper.config import Config
from daykeeper.mcp_server import build_server
from daykeeper.rpc import DaemonDown
from daykeeper.service import Service


class Backend:
    def __init__(self, svc):
        self.svc = svc

    def call(self, method, **params):
        return self.svc.call(method, **params)


class DownBackend:
    def call(self, method, **params):
        raise DaemonDown()


@pytest.fixture
def server(db, clock):
    return build_server(Backend(Service(db, Config(), clock)))


def text(result):
    return result.content[0].text


async def test_tools_cover_service(server):
    async with McpClient(server) as c:
        names = {t.name for t in (await c.list_tools()).tools}
    assert set(Service.METHODS) | {"plan_context"} <= names


async def test_tools_have_russian_descriptions(server):
    async with McpClient(server) as c:
        tools = {t.name: t for t in (await c.list_tools()).tools}
    assert "галочка" in tools["task_add"].description
    assert "duration_min" in tools["task_add"].input_schema["properties"]


async def test_quick_add_via_mcp(server):
    async with McpClient(server) as c:
        r = await c.call_tool("task_quick_add", {"text": "тренировка 2ч"})
        assert not r.is_error
        assert json.loads(text(r))["pomodoros"] == 2
        day = json.loads(text(await c.call_tool("day_get", {})))
    assert [t["title"] for t in day["tasks"]] == ["тренировка"]


async def test_service_error_is_tool_error(server):
    async with McpClient(server) as c:
        r = await c.call_tool("task_quick_add", {"text": "10:00-09:00 x"})
    assert r.is_error and "конец раньше начала" in text(r)


async def test_daemon_down_is_tool_error(db):
    async with McpClient(build_server(DownBackend())) as c:
        r = await c.call_tool("day_get", {})
    assert r.is_error and "демон не запущен" in text(r)


async def test_plan_context(server):
    async with McpClient(server) as c:
        await c.call_tool("task_quick_add", {"text": "зубы"})
        await c.call_tool("habit_add", {"title": "зарядка"})
        ctx = json.loads(text(await c.call_tool("plan_context", {"days": 3})))
    assert set(ctx) >= {"today", "tomorrow", "pending_summary", "recent", "goals", "habits"}
    assert ctx["today"]["day"] == "2026-10-18" and ctx["tomorrow"]["day"] == "2026-10-19"
    assert ctx["tomorrow"]["tasks"][0]["title"] == "зарядка"
