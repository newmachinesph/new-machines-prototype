"""The server-address rules for an org's own MCP server, applied on add, refresh and every call: https only;
the host resolved once per session, to public addresses only, and every request sent to that address (so DNS
rebinding cannot swap it); redirects never followed (`client.http_client`); 30 s per operation
(`client.TIMEOUT_S`); responses capped at 1 MB and never compressed (their size could not be bounded)."""

import ipaddress
import socket
from collections.abc import Callable
from dataclasses import dataclass

import httpx

HTTPS_PORT = 443
MAX_URL_LENGTH = 2048
MAX_PORT = 65535
MAX_RESPONSE_BYTES = 1024 * 1024
# Refused besides what `ipaddress` already calls non-global: NAT64 and 6to4 can carry any IPv4 address,
# private ones included, and the private ranges are listed so the rule reads on its own.
REFUSED_NETWORKS = tuple(
    ipaddress.ip_network(n)
    for n in (
        "0.0.0.0/8",
        "10.0.0.0/8",
        "100.64.0.0/10",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "198.18.0.0/15",
        "::1/128",
        "fc00::/7",
        "fe80::/10",
        "64:ff9b::/96",
        "64:ff9b:1::/48",
        "2002::/16",
    )
)

GLOBAL_UNICAST_V6 = ipaddress.ip_network("2000::/3")

type IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


class UrlRefused(Exception):
    """The address breaks a server-address rule. The message is a short reason code, never the address."""


class ResponseTooLarge(Exception):
    """The response passed MAX_RESPONSE_BYTES, or came compressed."""


@dataclass(frozen=True)
class Target:
    host: str  # as the URL names it, lower case (IDNA-encoded)
    port: int
    ip: str  # the checked public address every request of the session goes to


def is_public(ip: IPAddress) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if ip.is_multicast or not ip.is_global:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip not in GLOBAL_UNICAST_V6:
        return False  # IPv4-compatible, IPv4-translated, site-local and the rest of the non-public space
    return not any(ip in net for net in REFUSED_NETWORKS)


def check_url(url: str) -> tuple[str, int]:
    """(host, port) of an https URL with a host and no user name or password; UrlRefused otherwise."""
    if len(url) > MAX_URL_LENGTH:
        raise UrlRefused("too_long")
    try:
        parsed = httpx.URL(url)
    except httpx.InvalidURL:
        raise UrlRefused("malformed") from None
    if parsed.scheme != "https":
        raise UrlRefused("not_https")
    if parsed.userinfo:
        raise UrlRefused("credentials")
    if not parsed.host:
        raise UrlRefused("no_host")
    try:
        port = parsed.port
    except ValueError:  # httpx refuses some; keep the rule here too
        raise UrlRefused("malformed") from None
    if port is not None and not 0 < port <= MAX_PORT:
        raise UrlRefused("malformed")
    return parsed.host, port or HTTPS_PORT


def resolve(host: str, port: int) -> list[str]:
    """Every address `host` resolves to; OSError when it does not resolve. The tests replace this."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except UnicodeError:  # a malformed label (empty, over 63 characters); ValueError by ancestry
        raise UrlRefused("malformed") from None
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


def _literal(host: str) -> IPAddress | None:
    try:
        return ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return None


def target(url: str) -> Target:
    """Where the requests for `url` go: the first address of its host, when every address the host resolves
    to is public. Raises UrlRefused when a rule is broken, OSError when the host does not resolve."""
    host, port = check_url(url)
    literal = _literal(host)
    addresses = [str(literal)] if literal is not None else resolve(host, port)
    if not addresses:
        raise UrlRefused("no_address")
    checked: list[IPAddress] = []
    for address in addresses:
        ip = _literal(address)
        if ip is None or not is_public(ip):
            raise UrlRefused("not_public")
        checked.append(ip)
    return Target(host=host, port=port, ip=str(checked[0]))


class PinnedTransport(httpx.AsyncBaseTransport):
    """Sends every request for the target's host to the target's address. The host stays in the Host header
    and is the TLS server name, so the certificate is still checked against it. A request for another scheme,
    host or port is refused."""

    def __init__(self, target: Target, inner: httpx.AsyncBaseTransport) -> None:
        self._target, self._inner = target, inner

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        if (
            url.scheme != "https"
            or url.host != self._target.host
            or (url.port or HTTPS_PORT) != self._target.port
        ):
            raise UrlRefused("other_host")
        pinned = httpx.Request(
            request.method,
            url.copy_with(host=self._target.ip),
            headers=request.headers,
            stream=request.stream,
            extensions={**request.extensions, "sni_hostname": self._target.host},
        )
        return await self._inner.handle_async_request(pinned)

    async def aclose(self) -> None:
        await self._inner.aclose()


class _CappedStream(httpx.AsyncByteStream):
    def __init__(self, stream: httpx.AsyncByteStream, limit: int, on_exceed: Callable[[], None]) -> None:
        self._stream, self._limit, self._seen, self._on_exceed = stream, limit, 0, on_exceed

    async def __aiter__(self):
        async for chunk in self._stream:
            self._seen += len(chunk)
            if self._seen > self._limit:
                self._on_exceed()
                raise ResponseTooLarge("the response passed the size limit")
            yield chunk

    async def aclose(self) -> None:
        await self._stream.aclose()


class CappedTransport(httpx.AsyncBaseTransport):
    """Refuses a response that declares more than the limit (MAX_RESPONSE_BYTES unless given) or comes
    compressed, and stops one that streams past it. `on_exceed` is called first in each case: the MCP
    client swallows errors raised while it reads a body, so the session must be cancelled from outside."""

    def __init__(
        self,
        inner: httpx.AsyncBaseTransport,
        limit: int | None = None,
        on_exceed: Callable[[], None] | None = None,
    ) -> None:
        self._inner, self._limit = inner, limit
        self._on_exceed = on_exceed or (lambda: None)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        limit = MAX_RESPONSE_BYTES if self._limit is None else self._limit
        response = await self._inner.handle_async_request(request)
        declared = response.headers.get("content-length", "")
        encoding = response.headers.get("content-encoding", "identity").strip().lower()
        if (declared.isdigit() and int(declared) > limit) or encoding not in ("", "identity"):
            await response.aclose()
            self._on_exceed()
            raise ResponseTooLarge("the response is too large or compressed")
        return httpx.Response(
            status_code=response.status_code,
            headers=response.headers,
            stream=_CappedStream(response.stream, limit, self._on_exceed),
            extensions=response.extensions,
        )

    async def aclose(self) -> None:
        await self._inner.aclose()
