"""Lifecycle for an isolated loopback mock used by local evaluation and acceptance."""

import socket
import threading
from collections.abc import Iterator
from contextlib import contextmanager

import uvicorn

from omniagent.mock_service import create_mock_app


@contextmanager
def local_mock(database_url: str) -> Iterator[int]:
    ready = threading.Event()

    class Server(uvicorn.Server):
        async def startup(self, sockets: list[socket.socket] | None = None) -> None:
            await super().startup(sockets)
            ready.set()

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = int(listener.getsockname()[1])
    server = Server(
        uvicorn.Config(create_mock_app(database_url), log_level="critical", access_log=False)
    )
    worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    worker.start()
    try:
        if not ready.wait(10):
            raise RuntimeError("Local mock did not become ready")
        yield port
    finally:
        server.should_exit = True
        worker.join(10)
        listener.close()
        if worker.is_alive():
            raise RuntimeError("Local mock did not shut down")
