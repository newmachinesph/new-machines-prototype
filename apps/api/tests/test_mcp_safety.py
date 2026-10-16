"""The server-address rules, one test each: https only, public resolved addresses only, requests pinned to
the checked address, no redirects, 30 s, and 1 MB per response."""

import anyio
import httpx
import pytest

from app.custom_mcp import client, safety

URL = "https://mcp.acme.test/mcp"
PINNED = safety.Target("mcp.acme.test", 443, "93.184.216.34")


def _get(transport: httpx.AsyncBaseTransport, url: str = URL) -> httpx.Response:
    async def go() -> httpx.Response:
        async with httpx.AsyncClient(transport=transport) as http:
            return await http.get(url)

    return anyio.run(go)


@pytest.mark.parametrize(
    "url",
    [
        "http://mcp.acme.test/mcp",
        "ftp://mcp.acme.test/mcp",
        "mcp.acme.test/mcp",
        "https://user:pw@mcp.acme.test/mcp",
        "https:///mcp",
        "https://" + "a" * 2050 + ".test/",
    ],
)
def test_only_a_plain_https_address_is_taken(url):
    with pytest.raises(safety.UrlRefused):
        safety.check_url(url)


def test_an_https_address_gives_its_host_and_port():
    assert safety.check_url(URL) == ("mcp.acme.test", 443)
    assert safety.check_url("https://MCP.Acme.test:8443/x?y=1") == ("mcp.acme.test", 8443)


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",  # loopback
        "10.1.2.3",  # private
        "172.16.0.5",
        "192.168.1.1",
        "169.254.169.254",  # link-local, cloud metadata
        "100.64.0.1",  # CGNAT
        "0.0.0.0",
        "224.0.0.1",  # multicast
        "::1",
        "fd00::1",  # unique-local
        "fe80::1",  # link-local
        "::ffff:127.0.0.1",  # IPv4-mapped loopback
        "64:ff9b::a00:1",  # NAT64 of 10.0.0.1
        "2002:a00:1::1",  # 6to4 of 10.0.0.1
        "::a9fe:a9fe",  # IPv4-compatible 169.254.169.254
        "::7f00:1",  # IPv4-compatible 127.0.0.1
        "::ffff:0:a9fe:a9fe",  # IPv4-translated
        "::ffff:0:7f00:1",
        "fec0::1",  # deprecated site-local
    ],
)
def test_addresses_that_are_not_public_are_refused(ip):
    import ipaddress

    assert not safety.is_public(ipaddress.ip_address(ip))


@pytest.mark.parametrize("ip", ["93.184.216.34", "2001:4860:4860::8888", "2606:4700:4700::1111"])
def test_public_addresses_pass(ip):
    import ipaddress

    assert safety.is_public(ipaddress.ip_address(ip))


def test_a_host_that_resolves_to_a_private_address_is_refused(monkeypatch):
    monkeypatch.setattr(safety, "resolve", lambda host, port: ["10.0.0.5"])
    with pytest.raises(safety.UrlRefused):
        safety.target(URL)


def test_one_private_address_among_public_ones_is_enough_to_refuse(monkeypatch):
    monkeypatch.setattr(safety, "resolve", lambda host, port: ["93.184.216.34", "127.0.0.1"])
    with pytest.raises(safety.UrlRefused):
        safety.target(URL)


def test_an_address_literal_is_checked_without_resolving(monkeypatch):
    monkeypatch.setattr(safety, "resolve", lambda host, port: pytest.fail("resolved a literal"))
    for url in ("https://127.0.0.1/mcp", "https://[::1]/mcp", "https://169.254.169.254/latest"):
        with pytest.raises(safety.UrlRefused):
            safety.target(url)
    assert safety.target("https://93.184.216.34/mcp").ip == "93.184.216.34"


def test_the_target_pins_the_first_resolved_address(monkeypatch):
    monkeypatch.setattr(safety, "resolve", lambda host, port: ["93.184.216.34", "93.184.216.35"])
    assert safety.target(URL) == PINNED


def test_requests_go_to_the_pinned_address_with_the_host_kept():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={})

    target = safety.Target("mcp.acme.test", 443, "2001:4860:4860::8888")
    _get(safety.PinnedTransport(target, httpx.MockTransport(handler)))
    request = seen[0]
    assert str(request.url) == "https://[2001:4860:4860::8888]/mcp"
    assert request.headers["host"] == "mcp.acme.test"
    assert request.extensions["sni_hostname"] == "mcp.acme.test"


@pytest.mark.parametrize(
    "url", ["https://other.test/mcp", "http://mcp.acme.test/mcp", "https://mcp.acme.test:8443/mcp"]
)
def test_a_request_that_leaves_the_pinned_host_is_refused(url):
    transport = safety.PinnedTransport(PINNED, httpx.MockTransport(lambda r: httpx.Response(200)))
    with pytest.raises(safety.UrlRefused):
        _get(transport, url)


def test_the_client_follows_no_redirect_and_gives_up_after_30_seconds():
    assert client.TIMEOUT_S == 30
    http = client.http_client(PINNED, {})
    try:
        assert http.follow_redirects is False
        assert http.max_redirects == 0
        assert (http.timeout.connect, http.timeout.read, http.timeout.write, http.timeout.pool) == (
            30,
            30,
            30,
            30,
        )
        assert http.headers["accept-encoding"] == "identity"
    finally:
        anyio.run(http.aclose)


def test_a_response_over_1_mb_is_refused():
    assert safety.MAX_RESPONSE_BYTES == 1024 * 1024
    big = b"x" * (safety.MAX_RESPONSE_BYTES + 1)
    with pytest.raises(safety.ResponseTooLarge):
        _get(safety.CappedTransport(httpx.MockTransport(lambda r: httpx.Response(200, content=big))))


def test_a_streamed_response_is_cut_off_at_1_mb():
    async def chunks():
        for _ in range(3):
            yield b"x" * (512 * 1024)

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=chunks())

    with pytest.raises(safety.ResponseTooLarge):
        _get(safety.CappedTransport(httpx.MockTransport(handler)))


def test_a_compressed_response_is_refused_as_its_size_cannot_be_bounded():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x", headers={"content-encoding": "gzip"})

    with pytest.raises(safety.ResponseTooLarge):
        _get(safety.CappedTransport(httpx.MockTransport(handler)))


def test_a_response_of_exactly_1_mb_passes():
    exact = b"x" * safety.MAX_RESPONSE_BYTES
    response = _get(safety.CappedTransport(httpx.MockTransport(lambda r: httpx.Response(200, content=exact))))
    assert len(response.content) == safety.MAX_RESPONSE_BYTES


def test_the_token_goes_in_the_chosen_header():
    assert client.auth_headers("Authorization", "t1") == {"Authorization": "Bearer t1"}
    assert client.auth_headers("authorization", "t1") == {"Authorization": "Bearer t1"}
    assert client.auth_headers("X-Api-Key", "t1") == {"X-Api-Key": "t1"}


@pytest.mark.parametrize("url", ["https://" + "a" * 64 + ".test/", "https://a..test/"])
def test_a_malformed_host_name_is_refused_not_raised_as_a_unicode_error(url):
    with pytest.raises(safety.UrlRefused):
        safety.target(url)


@pytest.mark.parametrize(
    ("name", "token"),
    [
        ("X-Api-Key\r\nX-Evil: 1", "t1"),
        ("X-Api-Key", "t1\r\nX-Evil: 1"),
        ("X-Api-Key", ""),
        ("X-Api-Key", "a" * 4097),
        ("X-Api-Key", "has space"),
        ("Host", "t1"),
        ("cookie", "t1"),
        ("", "t1"),
    ],
)
def test_a_header_name_or_token_that_could_smuggle_is_refused(name, token):
    with pytest.raises(safety.UrlRefused):
        client.auth_headers(name, token)


def test_an_ordinary_header_name_is_accepted():
    assert client.auth_headers("X-Api-Key", "t1") == {"X-Api-Key": "t1"}


@pytest.mark.parametrize("url", ["https://mcp.acme.test:65536/mcp", "https://mcp.acme.test:99999/mcp"])
def test_a_port_above_65535_is_refused(url):
    with pytest.raises(safety.UrlRefused):
        safety.check_url(url)
