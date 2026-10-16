"""Sealing the tokens of the orgs' own MCP servers with AES-GCM under NM_SECRETS_KEY. A sealed token is
nonce + ciphertext, bound to a context (the server id) so it cannot be moved to another row. Without a usable
key nothing is sealed or opened: callers fail closed. Never log a token or a sealed value."""

import base64
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app import settings

NONCE_BYTES = 12
KEY_BYTES = 32


class SecretsUnavailable(Exception):
    """NM_SECRETS_KEY is missing or is not 32 bytes of URL-safe base64."""


class SecretUnreadable(Exception):
    """A sealed value that does not open with this key and context."""


def _key() -> bytes:
    raw = settings.secrets_key()
    if not raw:
        raise SecretsUnavailable("NM_SECRETS_KEY is not set")
    try:
        key = base64.urlsafe_b64decode(raw.encode("ascii") + b"=" * (-len(raw) % 4))
    except ValueError:
        raise SecretsUnavailable("NM_SECRETS_KEY is not URL-safe base64") from None
    if len(key) != KEY_BYTES:
        raise SecretsUnavailable("NM_SECRETS_KEY must decode to 32 bytes")
    return key


def require_key() -> None:
    """Raise SecretsUnavailable unless a usable key is configured."""
    _key()


def seal(secret: str, context: str) -> bytes:
    nonce = os.urandom(NONCE_BYTES)
    return nonce + AESGCM(_key()).encrypt(nonce, secret.encode("utf-8"), context.encode("utf-8"))


def open_sealed(sealed: bytes, context: str) -> str:
    key = _key()
    if len(sealed) <= NONCE_BYTES:
        raise SecretUnreadable("the sealed value is too short")
    try:
        plain = AESGCM(key).decrypt(sealed[:NONCE_BYTES], sealed[NONCE_BYTES:], context.encode("utf-8"))
    except InvalidTag:
        raise SecretUnreadable("the sealed value does not open with this key and context") from None
    return plain.decode("utf-8")


def last4(secret: str) -> str:
    """What the web shows of a token: its last 4 characters."""
    return secret[-4:]
