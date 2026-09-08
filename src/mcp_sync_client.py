import threading
import asyncio

from src.mcp_client import MCPClient


class SyncMCPClient:
    def __init__(self, client: MCPClient):
        self._client = client
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._started = threading.Event()

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()
        self._loop.close()

    def _run(self, coro, timeout=None):
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    async def _session(self):
        self._stop_event = asyncio.Event()
        await self._client.connect()
        self._started.set()
        try:
            await self._stop_event.wait()
        finally:
            await self._client.disconnect()

    def start(self):
        self._thread.start()
        self._session_future = asyncio.run_coroutine_threadsafe(
            self._session(), self._loop
        )
        if not self._started.wait(timeout=10):
            raise RuntimeError("Error while starting MCP session")

    def stop(self):
        self._loop.call_soon_threadsafe(self._stop_event.set)
        self._session_future.result(timeout=10)
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join()

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        attr = getattr(self._client, name)
        if not callable(attr):
            return attr

        def sync_wrapper(*args, **kwargs):
            return self._run(attr(*args, **kwargs))

        return sync_wrapper
