"""Quiet logging for the MCP clients (the org's own servers and the platform's). httpx logs every request's
full address at INFO and the SDK logs session ids and, on failures, tracebacks whose text holds the address:
an address can carry a key in its query, and the platform's holds a host only the deployment should know.
Importing this module applies the rules, so they hold in the API and the worker whatever the process sets for
the root logger."""

import logging

QUIET = ("httpx", "httpcore", "mcp")
# A logger's filters see only its own records, so each SDK module that logs exceptions gets one.
SDK_MODULES = ("mcp.client.streamable_http", "mcp.client.session", "mcp.shared.session")


class NoTraceback(logging.Filter):
    """The SDK logs some failures with their traceback, and an httpx status error's text holds the full
    address. Keep the record, but only the failure's type name."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.exc_info and record.exc_info[1] is not None:
            record.msg = f"{record.getMessage()}: {type(record.exc_info[1]).__name__}"
            record.args = None
        record.exc_info = None
        record.exc_text = None
        return True


def quiet() -> None:
    """Apply the rules; safe to call again (a filter is added once per logger)."""
    for name in QUIET:
        logging.getLogger(name).setLevel(logging.WARNING)
    # Some of the SDK's warnings put a redirect target or the raw result in an f-string no filter can clean.
    logging.getLogger("mcp.client.streamable_http").setLevel(logging.ERROR)
    for name in SDK_MODULES:
        logger = logging.getLogger(name)
        if not any(isinstance(f, NoTraceback) for f in logger.filters):
            logger.addFilter(NoTraceback())


quiet()
