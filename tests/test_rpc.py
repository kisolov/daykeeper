import asyncio

import pytest

from daykeeper.config import Config
from daykeeper.rpc import Client, DaemonDown, serve
from daykeeper.service import Service, ServiceError


@pytest.fixture
async def server(tmp_path, db, clock):
    svc = Service(db, Config(), clock)
    path = tmp_path / "dk.sock"
    srv = await serve(svc, path)
    yield svc, srv, path
    await srv.close()


async def test_rpc_roundtrip(server):
    _, _, path = server
    client = Client(path)
    await client.acall("task_quick_add", text="зубы")
    day = await client.acall("day_get")
    assert [t["title"] for t in day["tasks"]] == ["зубы"]


async def test_sync_call_from_thread(server):
    _, _, path = server
    day = await asyncio.to_thread(Client(path).call, "day_get")
    assert day["tasks"] == []


async def test_rpc_error(server):
    _, _, path = server
    client = Client(path)
    await client.acall("task_add", title="утро", kind="timed", start="09:00", end="10:00")
    ev = await client.acall("task_add", title="вечер", kind="timed", start="19:00", end="20:00")
    with pytest.raises(ServiceError, match="не может стоять выше"):
        await client.acall("task_move", task_id=ev["id"], index=0)


async def test_subscribe_pushes_on_change(server):
    _, _, path = server
    client = Client(path)
    t = await client.acall("task_quick_add", text="код 1ч")
    stream = client.subscribe()
    first = await asyncio.wait_for(anext(stream), 1)
    assert first["timer"] is None and first["day"]["total"] == 1
    await client.acall("timer_start", task_id=t["id"])
    pushed = await asyncio.wait_for(anext(stream), 1)
    assert pushed["timer"]["running"] is True
    await stream.aclose()


async def test_publish_reaches_subscribers(server):
    _, srv, path = server
    stream = Client(path).subscribe()
    await asyncio.wait_for(anext(stream), 1)
    await srv.publish()
    assert "timer" in await asyncio.wait_for(anext(stream), 1)
    await stream.aclose()


async def test_malformed_line(server):
    _, _, path = server
    reader, writer = await asyncio.open_unix_connection(str(path))
    writer.write(b"not json\n")
    await writer.drain()
    line = await asyncio.wait_for(reader.readline(), 1)
    assert b'"invalid"' in line
    writer.close()


def test_client_daemon_down(tmp_path):
    with pytest.raises(DaemonDown, match="демон не запущен"):
        Client(tmp_path / "no.sock").call("day_get")


async def test_async_client_daemon_down(tmp_path):
    with pytest.raises(DaemonDown):
        await Client(tmp_path / "no.sock").acall("day_get")


async def test_stalled_subscriber_does_not_block_publish(server):
    svc, srv, _ = server

    class Stalled:
        closed = False

        def write(self, data):
            pass

        async def drain(self):
            await asyncio.sleep(3600)

        def close(self):
            self.closed = True

    stalled = Stalled()
    srv.subscribers.add(stalled)
    await asyncio.wait_for(srv.publish(), 3)
    assert stalled not in srv.subscribers and stalled.closed
