"""Sealing tokens with AES-GCM under NM_SECRETS_KEY: a round trip, the server id as context, and no key, a
bad key or a changed ciphertext fails closed."""

import base64

import pytest

from app import secrets_box

KEY = base64.urlsafe_b64encode(bytes(range(32))).decode("ascii")
TOKEN = "secret-token-1234"


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setenv("NM_SECRETS_KEY", KEY)


def test_a_sealed_token_opens_with_the_same_context():
    sealed = secrets_box.seal(TOKEN, "mcp_0123456789ab")
    assert TOKEN.encode() not in sealed
    assert len(sealed) > secrets_box.NONCE_BYTES
    assert secrets_box.open_sealed(sealed, "mcp_0123456789ab") == TOKEN


def test_each_seal_uses_a_fresh_nonce():
    assert secrets_box.seal(TOKEN, "mcp_a") != secrets_box.seal(TOKEN, "mcp_a")


def test_another_context_or_a_changed_byte_does_not_open():
    sealed = secrets_box.seal(TOKEN, "mcp_0123456789ab")
    with pytest.raises(secrets_box.SecretUnreadable):
        secrets_box.open_sealed(sealed, "mcp_ffffffffffff")
    changed = sealed[:-1] + bytes([sealed[-1] ^ 1])
    with pytest.raises(secrets_box.SecretUnreadable):
        secrets_box.open_sealed(changed, "mcp_0123456789ab")
    with pytest.raises(secrets_box.SecretUnreadable):
        secrets_box.open_sealed(b"short", "mcp_0123456789ab")


@pytest.mark.parametrize("value", [None, "", "not base64 !", base64.urlsafe_b64encode(b"short").decode()])
def test_a_missing_or_bad_key_fails_closed(monkeypatch, value):
    sealed = secrets_box.seal(TOKEN, "mcp_a")
    if value is None:
        monkeypatch.delenv("NM_SECRETS_KEY")
    else:
        monkeypatch.setenv("NM_SECRETS_KEY", value)
    with pytest.raises(secrets_box.SecretsUnavailable):
        secrets_box.require_key()
    with pytest.raises(secrets_box.SecretsUnavailable):
        secrets_box.seal(TOKEN, "mcp_a")
    with pytest.raises(secrets_box.SecretsUnavailable):
        secrets_box.open_sealed(sealed, "mcp_a")


def test_a_key_without_padding_is_read():
    stripped = KEY.rstrip("=")
    assert base64.urlsafe_b64decode(stripped + "=" * (-len(stripped) % 4)) == bytes(range(32))


def test_only_the_last_4_characters_are_kept_for_display():
    assert secrets_box.last4(TOKEN) == "1234"
    assert secrets_box.last4("ab") == "ab"
