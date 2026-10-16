"""An org's own MCP servers (custom connectors), as the API shows and takes them. The token goes in, never
out: responses carry its last 4 characters only."""

import unicodedata
from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from app.custom_mcp.client import HEADER_NAME as HEADER_NAME_RE
from app.custom_mcp.client import is_reserved_header
from app.models.common import Model, Opt, RequestModel

McpToolClass = Literal["read", "write", "blocked"]
McpToolReason = Literal[
    "marked_read_only",
    "changes_data",
    "changes_access",
    "marked_destructive",
    "deletes",
    "moves_money",
    "reserved_name",
    "schema_unusable",
    "schema_too_large",
]
McpServerStatus = Literal["active", "failing", "removed"]
McpServerError = Literal["unreachable", "address_refused"]
HEADER_NAME = HEADER_NAME_RE.pattern  # RFC 9110 token, 1-64 characters
HIDDEN_CATEGORIES = frozenset({"Cf", "Cc", "Co", "Cn"})  # zero-width, bidi, control, private-use, unassigned
# Letters that draw nothing. NFKC turns U+3164 and U+FFA0 into U+1160, so that one is listed too.
BLANK_LETTERS = frozenset({"\u3164", "\u2800", "\u1160", "\u115f", "\uffa0"})
NAME_MAX = 60
TOKEN_PATTERN = r"^[!-~]{9,4096}$"  # visible ASCII; 9+ so the last 4 shown are never most of the token


def _one_line(value: str) -> str:
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("must be one line of text")
    return value


def _header(value: str) -> str:
    if is_reserved_header(value):
        raise ValueError("this header cannot carry the token")
    return value


class McpTool(Model):
    id: str
    name: str  # the tool's MCP name
    description: str
    tool_class: McpToolClass  # read: runs freely; write: asks first; blocked: never offered
    why: McpToolReason
    on: bool


class McpServer(Model):
    id: str
    name: str
    url: str  # without its query or fragment
    header_name: str
    token_last4: str | Opt = None
    status: McpServerStatus
    connector_key: str
    tool_count: int  # the tools packs can use: switched on and not blocked
    tools: list[McpTool]
    tools_listed_at: datetime | Opt = None
    last_error: McpServerError | Opt = None
    created_at: datetime


class AddMcpServerRequest(RequestModel):
    """`headerName` Authorization (the default) sends `Bearer <token>`; any other header sends the token
    as it is."""

    name: str = Field(min_length=1, max_length=NAME_MAX)
    url: str = Field(min_length=1, max_length=2048)
    header_name: str = Field(default="Authorization", pattern=HEADER_NAME)
    token: str = Field(pattern=TOKEN_PATTERN, repr=False)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        stripped = unicodedata.normalize("NFKC", _one_line(value)).strip()
        if any(unicodedata.category(c) in HIDDEN_CATEGORIES or c in BLANK_LETTERS for c in stripped):
            raise ValueError("must not contain invisible or control characters")
        if not stripped:
            raise ValueError("must not be blank")
        if len(stripped) > NAME_MAX:  # NFKC can make a name longer
            raise ValueError(f"must be at most {NAME_MAX} characters")
        return stripped

    @field_validator("url")
    @classmethod
    def _url(cls, value: str) -> str:
        return _one_line(value).strip()

    @field_validator("header_name")
    @classmethod
    def _header_name(cls, value: str) -> str:
        return _header(value)


class ReplaceMcpTokenRequest(RequestModel):
    token: str = Field(pattern=TOKEN_PATTERN, repr=False)
