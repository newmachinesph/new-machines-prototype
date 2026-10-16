"""Words that say what a tool does, shared by the Composio importer (scripts/import_connector.py) and the
sorting of an org's own MCP tools (`custom_mcp.tools`), so both block the same deletes and money moves."""

import re

READ_VERBS = {
    "GET",
    "LIST",
    "FIND",
    "SEARCH",
    "LOOKUP",
    "LOOK",
    "QUERY",
    "FETCH",
    "READ",
    "RETRIEVE",
    "DOWNLOAD",
    "EXPORT",
    "AGGREGATE",
    "COUNT",
}
WRITE_WORDS = {
    "REPLACE",
    "UPDATE",
    "UPSERT",
    "SET",
    "CREATE",
    "ADD",
    "INSERT",
    "APPEND",
    "MOVE",
    "COPY",
    "SORT",
    "SEND",
    "FORWARD",
    "REPLY",
    "POST",
    "PUT",
    "PATCH",
    "MODIFY",
    "RUN",
    "EXECUTE",
    "SHARE",
    "INVITE",
    "IMPORT",
    "UPLOAD",
    "SUBMIT",
    "PUBLISH",
    "COMPLETE",
    "INSTALL",
}
DELETE_WORDS = {
    "DELETE",
    "CLEAR",
    "REMOVE",
    "TRASH",
    "DESTROY",
    "PURGE",
    "ARCHIVE",
    "CANCEL",
    "VOID",
    "DETACH",
    "EXPIRE",
    "CLOSE",
    "REVOKE",
    "DISABLE",
}
MONEY_WORDS = {
    "PAY",
    "PAID",
    "PAYMENT",
    "PAYMENTS",
    "PAYOUT",
    "PAYOUTS",
    "REFUND",
    "REFUNDS",
    "CHARGE",
    "CHARGES",
    "TRANSFER",
    "TRANSFERS",
    "TRANSACTION",
    "TRANSACTIONS",
    "CHECKOUT",
    "CAPTURE",
    "CONFIRM",
    "FINALIZE",
    "TOPUP",
    "BALANCE",
    "CREDIT",
    "INVOICE",
    "INVOICES",
    "SUBSCRIPTION",
    "SUBSCRIPTIONS",
    "ORDER",
    "ORDERS",
    "GIFT",
    "FULFILL",
}
# Money verbs: a name that starts with a read verb but carries one of these does something, it is no read.
MONEY_VERBS = {"PAY", "CAPTURE", "CONFIRM", "FINALIZE", "CHECKOUT", "TOPUP", "FULFILL"}
# Words of actions that change who can reach data: shared, invited, watched from outside or sent as someone.
# Unless they plainly read, they wait for a person to review them.
ACCESS_WORDS = {
    "SHARE",
    "SHARING",
    "INVITE",
    "ACL",
    "PERMISSION",
    "PERMISSIONS",
    "WATCH",
    "FORWARDING",
    "DELEGATE",
}
# Split at lower->Upper, acronym->Word ("HTTPDelete") and letter<->digit ("Delete2Items") boundaries.
_CAMEL = re.compile(
    r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])|(?<=[A-Za-z])(?=[0-9])|(?<=[0-9])(?=[A-Za-z])"
)
_NOT_ALNUM = re.compile(r"[^A-Za-z0-9]+")


def name_words(name: str) -> list[str]:
    """A tool name's words, upper case: "getCustomer" and "get-customer" -> GET, CUSTOMER."""
    return [w.upper() for w in _NOT_ALNUM.split(_CAMEL.sub(" ", name)) if w]


def plainly_reads(found: list[str]) -> bool:
    """Whether a name's words plainly read: a read verb first (or BATCH GET) and no write or money verb."""
    return (
        bool(found)
        and (found[0] in READ_VERBS or found[:2] == ["BATCH", "GET"])
        and not (WRITE_WORDS | MONEY_VERBS) & set(found)
    )


def example(schema, defs: dict | None = None, depth: int = 0):
    """A plausible value for `schema`, for a generated sandbox response; `defs` resolves #/$defs/ refs."""
    if not isinstance(schema, dict) or depth > 8:
        return None
    defs = defs or {}
    ref = schema.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/$defs/"):
        rest = {k: v for k, v in schema.items() if k != "$ref"}
        return example({**(defs.get(ref.rsplit("/", 1)[-1]) or {}), **rest}, defs, depth + 1)
    if schema.get("allOf"):
        merged = {k: v for k, v in schema.items() if k != "allOf"}
        for part in schema["allOf"]:
            merged.update(part if isinstance(part, dict) else {})
        return example(merged, defs, depth + 1)
    if schema.get("examples"):
        return schema["examples"][0]
    if "enum" in schema and schema["enum"]:
        return schema["enum"][0]
    for branch in schema.get("anyOf") or schema.get("oneOf") or []:
        if isinstance(branch, dict) and branch.get("type") != "null":
            return example(branch, defs, depth + 1)
    kind = schema.get("type")
    kind = next((k for k in kind if k != "null"), None) if isinstance(kind, list) else kind
    if kind == "object" or "properties" in schema:
        return {k: example(v, defs, depth + 1) for k, v in (schema.get("properties") or {}).items()}
    if kind == "array":
        item = example(schema.get("items") or {}, defs, depth + 1)
        return [] if item is None else [item]
    return {"string": "sample", "integer": 1, "number": 1, "boolean": True}.get(kind)
