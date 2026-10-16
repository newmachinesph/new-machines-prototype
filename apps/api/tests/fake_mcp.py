"""An in-process MCP server for the custom-connector tests: FastMCP over streamable HTTP on 127.0.0.1, reached
through the client's real pinning and cap. The `fake_mcp` fixture makes every host resolve to PUBLIC_IP, hands
each pinned request to the local server (recording what the client sent), gives up after 5 s instead of 30,
and seals tokens with TEST_KEY. A token guard answers 401 unless the request carries a token in `tokens`
(as a Bearer token or an x-api-key header); /moved answers a redirect to /mcp."""

import base64
import socket
import threading
import time

import httpx
import pytest
import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import BaseModel

from app.custom_mcp import client, safety

HOST = "mcp.acme.test"
URL = f"https://{HOST}/mcp"
PUBLIC_IP = "93.184.216.34"
TOKEN = "secret-token-1234"
FRESH_TOKEN = "fresh-token-5678"
TEST_KEY = base64.urlsafe_b64encode(bytes(range(32))).decode("ascii")
READ_ONLY = ToolAnnotations(readOnlyHint=True)
START_WAIT_S = 5.0
TEST_TIMEOUT_S = 5.0


class Customer(BaseModel):
    id: str
    name: str
    email: str


def _server(name: str) -> FastMCP:
    # The requests carry Host: mcp.acme.test, so the server's own DNS-rebinding guard is off.
    return FastMCP(
        name,
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )


def acme_server() -> FastMCP:
    """Six tools: three that read (one fails), one that writes, one marked destructive, one moving money."""
    server = _server("Acme CRM")

    @server.tool(annotations=READ_ONLY, description="Look up a customer by id.")
    def get_customer(customer_id: str) -> Customer:
        return Customer(id=customer_id, name="Ada Lovelace", email="ada@example.com")

    @server.tool(annotations=READ_ONLY, description="List the order ids of a customer.")
    def list_orders(customer_id: str) -> list[str]:
        return [f"{customer_id}-o1"]

    @server.tool(description="Replace the note on a customer.")
    def update_customer_note(customer_id: str, note: str) -> str:
        return f"noted {customer_id}: {note}"

    @server.tool(annotations=ToolAnnotations(destructiveHint=True), description="Delete a customer.")
    def delete_customer(customer_id: str) -> str:
        return "deleted"

    @server.tool(description="Refund a payment.")
    def refund_payment(payment_id: str) -> str:
        return "refunded"

    @server.tool(annotations=READ_ONLY, description="Read the weekly report.")
    def get_broken_report() -> str:
        raise ToolError("report service is down")

    return server


def _item() -> str:
    return "item"


def many_server(count: int) -> FastMCP:
    server = _server("Many tools")
    for n in range(count):
        server.add_tool(_item, name=f"get_item_{n:03d}", description="Read one item.", annotations=READ_ONLY)
    return server


async def _respond(send, status: int, headers: list[tuple[bytes, bytes]] | None = None) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-length", b"0"), *(headers or [])],
        }
    )
    await send({"type": "http.response.body", "body": b""})


class FakeMcp:
    """One running fake server and what reached it."""

    def __init__(self, server: FastMCP) -> None:
        self.server = server
        self.tokens = {TOKEN}
        self.paths: list[str] = []  # request paths the server saw
        self.hosts: list[str] = []  # Host headers the client sent
        self.urls: list[str] = []  # URLs the client sent, after pinning
        self.sni: list[str | None] = []  # TLS server names the client asked for
        self.port = 0
        self._inner = None
        self._uvicorn: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http":
            self.paths.append(scope["path"])
            if scope["path"] == "/moved":
                await _respond(send, 307, [(b"location", b"/mcp")])
                return
            headers = dict(scope["headers"])
            bearer = headers.get(b"authorization", b"").decode().removeprefix("Bearer ")
            api_key = headers.get(b"x-api-key", b"").decode()
            if bearer not in self.tokens and api_key not in self.tokens:
                await _respond(send, 401)
                return
        await self._inner(scope, receive, send)

    def start(self) -> FakeMcp:
        self._inner = self.server.streamable_http_app()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        self.port = sock.getsockname()[1]
        config = uvicorn.Config(self, log_level="warning", lifespan="on", timeout_graceful_shutdown=1)
        self._uvicorn = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._uvicorn.run, kwargs={"sockets": [sock]}, daemon=True)
        self._thread.start()
        deadline = time.monotonic() + START_WAIT_S
        while not self._uvicorn.started:
            if time.monotonic() > deadline:
                raise RuntimeError("the fake MCP server did not start")
            time.sleep(0.02)
        return self

    def stop(self) -> None:
        if self._uvicorn is not None:
            self._uvicorn.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=5)


class _LocalTransport(httpx.AsyncBaseTransport):
    """Stands in for the network under the client's pinning: records the request, then sends it over plain
    HTTP to the fake server's port."""

    def __init__(self, fake: FakeMcp) -> None:
        self._fake = fake
        self._inner = httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self._fake.urls.append(str(request.url))
        self._fake.hosts.append(request.headers.get("host", ""))
        self._fake.sni.append(request.extensions.get("sni_hostname"))
        local = request.url.copy_with(scheme="http", host="127.0.0.1", port=self._fake.port)
        extensions = {k: v for k, v in request.extensions.items() if k != "sni_hostname"}
        forwarded = httpx.Request(
            request.method, local, headers=request.headers, stream=request.stream, extensions=extensions
        )
        return await self._inner.handle_async_request(forwarded)

    async def aclose(self) -> None:
        await self._inner.aclose()


def start_fake(monkeypatch: pytest.MonkeyPatch, server: FastMCP) -> FakeMcp:
    """Serve `server` and point the client at it (see the module docstring). Stop it when the test ends."""
    fake = FakeMcp(server).start()
    monkeypatch.setattr(safety, "resolve", lambda host, port: [PUBLIC_IP])
    monkeypatch.setattr(client, "_inner_transport", lambda: _LocalTransport(fake))
    monkeypatch.setattr(client, "TIMEOUT_S", TEST_TIMEOUT_S)
    monkeypatch.setenv("NM_SECRETS_KEY", TEST_KEY)
    return fake


@pytest.fixture
def fake_mcp(monkeypatch):
    fake = start_fake(monkeypatch, acme_server())
    yield fake
    fake.stop()
