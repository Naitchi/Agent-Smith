from concurrent.futures import Future
from typing import Any, Optional
import threading
import asyncio

from src.mcp_client import MCPClient


class SyncMCPClient:
    def __init__(self, client: MCPClient) -> None:
        self._client: MCPClient = client
        self._loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()
        self._thread: threading.Thread = threading.Thread(
            target=self._run_loop, daemon=True
        )
        self._started: threading.Event = threading.Event()
        self._stop_event: Optional[asyncio.Event] = None
        self._session_future: Optional[Future[None]] = None

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()
        self._loop.close()

    def _run(self, coro: Any, timeout: Optional[int] = None) -> Any:
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    async def _session(self) -> None:
        self._stop_event = asyncio.Event()
        await self._client.connect()
        self._started.set()
        try:
            await self._stop_event.wait()
        finally:
            await self._client.disconnect()

    def start(self) -> None:
        self._thread.start()
        self._session_future = asyncio.run_coroutine_threadsafe(
            self._session(), self._loop
        )
        if not self._started.wait(timeout=10):
            raise RuntimeError("Error while starting MCP session")

    def stop(self) -> None:
        if self._stop_event is not None:
            self._loop.call_soon_threadsafe(self._stop_event.set)
        if self._session_future is not None:
            self._session_future.result(timeout=10)
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join()

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        attr = getattr(self._client, name)
        if not callable(attr):
            return attr

        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            return self._run(attr(*args, **kwargs))

        return sync_wrapper
