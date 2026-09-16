"""Synchronous façade over the async `MCPClient`.

Runs its own event loop on a dedicated background thread, so a
synchronous caller (the Sandbox's bridge thread, itself running in the
multiprocessing parent process) can drive the async `MCPClient` without
becoming async itself.
"""

import asyncio
import threading
from concurrent.futures import Future
from typing import Any

from src.mcp_client import MCPClient


class SyncMCPClient:
    """Runs one `MCPClient` session on a dedicated thread + event loop.

    `start()`/`stop()` bring the session up/down. Once running, any
    method of the wrapped `MCPClient` (`get_tools_list`, `use_tool`,
    ...) can be called directly on this object: `__getattr__` looks the
    name up on the wrapped client and, if it's callable, returns a
    synchronous wrapper that runs it on the background loop and blocks
    for the result — so `sync_client.use_tool(...)` behaves like a
    normal blocking call from the caller's point of view.
    """

    def __init__(self, client: MCPClient) -> None:
        """Args:
        client: The `MCPClient` this instance will drive. Not
            connected yet — call `start()` for that.
        """
        self._client: MCPClient = client
        self._loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()
        self._thread: threading.Thread = threading.Thread(
            target=self._run_loop, daemon=True
        )
        self._started: threading.Event = threading.Event()
        self._stop_event: asyncio.Event | None = None
        self._session_future: Future[None] | None = None
        self._running: bool = False

    def _run_loop(self) -> None:
        """Thread target: make `self._loop` current and run it forever.

        Runs until something schedules `self._loop.stop()` on it (from
        `start()`'s failure path, or from `stop()`), at which point the
        loop is closed and the thread exits.
        """
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()
        self._loop.close()

    def _run(self, coro: Any, timeout: int | None = 300) -> Any:
        """Run a coroutine on the background loop and block for its result.

        Args:
            coro: The coroutine to run — scheduled on `self._loop` from
                whichever thread calls this.
            timeout: Seconds to wait for a result before raising.

        Returns:
            The coroutine's return value.
        """
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    async def _session(self) -> None:
        """Coroutine holding the MCP connection open until told to stop.

        Connects `self._client`, signals `self._started` so `start()`
        can return, then waits on `self._stop_event` — disconnecting in
        a `finally` so the client is always cleanly closed, even if
        something goes wrong while waiting.
        """
        self._stop_event = asyncio.Event()
        await self._client.connect()
        self._started.set()
        try:
            await self._stop_event.wait()
        finally:
            await self._client.disconnect()

    def start(self) -> None:
        """Start the background thread and connect the MCP client.

        Blocks until `_session()` has actually connected (or 10s
        elapse).

        Raises:
            RuntimeError: If already running, or if the session fails
                to start within the timeout — in which case the loop
                and thread are torn down before raising.
        """
        if self._running:
            raise RuntimeError("MCP session is already running")
        self._thread.start()
        self._session_future = asyncio.run_coroutine_threadsafe(
            self._session(), self._loop
        )
        if not self._started.wait(timeout=10):
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=5)
            raise RuntimeError(
                "Error while starting MCP session, "
                "could not launch the session"
            )
        self._running = True

    def stop(self) -> None:
        """Signal `_session()` to disconnect, then stop the background loop.

        A no-op if not currently running. Always joins the background
        thread (with a timeout) before returning, even if waiting for
        the session's own shutdown raises.

        Raises:
            RuntimeError: If waiting for `_session()` to finish
                disconnecting fails.
        """
        if not self._running:
            return
        if self._stop_event is not None:
            self._loop.call_soon_threadsafe(self._stop_event.set)
        try:
            if self._session_future is not None:
                self._session_future.result(timeout=10)
        except Exception as e:
            raise RuntimeError(
                "Error while stopping MCP session, "
                "could not stop the session"
            ) from e
        finally:
            try:
                self._loop.call_soon_threadsafe(self._loop.stop)
            except RuntimeError:
                pass
            self._thread.join(timeout=5)
            self._running = False

    def __getattr__(self, name: str) -> Any:
        """Delegate any public attribute lookup to the wrapped `MCPClient`.

        Args:
            name: Attribute name being looked up (only reached for
                names not already defined on `SyncMCPClient` itself).

        Returns:
            `getattr(self._client, name)` directly if it isn't
            callable, or a synchronous wrapper around it (running it on
            the background loop via `_run`) if it is — e.g.
            `sync_client.use_tool(...)` transparently becomes a
            blocking call.

        Raises:
            AttributeError: For any name starting with ``_`` (private
                attributes are never delegated).
            RuntimeError: If the session isn't running yet.
        """
        if name.startswith("_"):
            raise AttributeError(name)
        if not self._running:
            raise RuntimeError("MCP session is not running")
        attr = getattr(self._client, name)
        if not callable(attr):
            return attr

        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            return self._run(attr(*args, **kwargs))

        return sync_wrapper
