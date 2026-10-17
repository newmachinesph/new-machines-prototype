"""Model providers: one call = system + messages + tools -> content blocks + usage.

`fake` is scripted per agent (tests and NM_MODEL_ENV=test); `vertex` calls Gemini on Vertex AI through the
google-genai SDK. Profiles in models.yaml pick the provider and model per environment and carry the price used
for spend.
"""

import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from functools import cache
from typing import Any, Protocol

from app import settings

SUBMIT_TOOL = "submit_result"
AGENT_MARKER = "agent:"
INPUTS_HEADING = "# Inputs"
MAX_TOKENS_CAP = 16000  # every model in models.yaml allows more; non-streaming calls stay short
FAKE_INPUT_TOKENS = 1200
FAKE_OUTPUT_TOKENS = 300
_TOKENS_PER_PRICE_UNIT = 1_000_000  # prices are minor units per million tokens
# One model call = one Temporal activity. The HTTP call must give up before the activity times out, or a
# retried activity would overlap a call that is still running (double spend, a worker thread tied up).
MODEL_ACTIVITY_TIMEOUT_S = 120
MODEL_CALL_TIMEOUT_S = MODEL_ACTIVITY_TIMEOUT_S - 20


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict


@dataclass
class ModelTurn:
    content: list[dict]  # {"type": "text", "text"} | {"type": "tool_use", "id", "name", "input"}
    stop_reason: str
    input_tokens: int
    output_tokens: int
    model: str


class ModelProvider(Protocol):
    def call(
        self, *, model: str, system: str, messages: list[dict], tools: list[ToolSpec], max_tokens: int
    ) -> ModelTurn: ...


# --- profiles and cost -----------------------------------------------------------------------------


def _profile(models_def: dict, profile: str) -> dict:
    profiles = models_def.get("profiles") or {}
    if profile not in profiles:
        raise ValueError(f"unknown model profile {profile!r}")
    return profiles[profile]


def provider_for(profile: str, models_def: dict, env: str) -> tuple[ModelProvider, str]:
    """Provider and model id for `profile` in environment `env` (test | dev | prod)."""
    entry = (_profile(models_def, profile).get("envs") or {}).get(env)
    if not entry:
        raise ValueError(f"model profile {profile!r} has no entry for env {env!r}")
    if entry["provider"] == "fake":
        return FakeProvider(), entry["model"]
    if entry["provider"] == "vertex":
        return VertexProvider(), entry["model"]
    raise ValueError(f"unknown model provider {entry['provider']!r}")


def cost_minor(models_def: dict, profile: str, input_tokens: int, output_tokens: int) -> int:
    """Cost in minor units, rounded up: tokens x price per million tokens."""
    price = _profile(models_def, profile)["price_per_mtok"]
    total = input_tokens * price["input_minor"] + output_tokens * price["output_minor"]
    return -(-total // _TOKENS_PER_PRICE_UNIT)


# --- vertex ----------------------------------------------------------------------------------------

_MS_PER_S = 1000


@cache
def _shared_client():
    from google import genai
    from google.genai import types

    # Retries belong to Temporal (activity retry policy): without retry_options the SDK never retries.
    # Credentials are Application Default Credentials (the Cloud Run service account, or gcloud locally).
    return genai.Client(
        vertexai=True,
        project=settings.vertex_project(),
        location=settings.vertex_location(),
        http_options=types.HttpOptions(timeout=MODEL_CALL_TIMEOUT_S * _MS_PER_S),
    )


def _tool_names(messages: list[dict]) -> dict[str, str]:
    """tool_use id -> tool name: a function response names its function, a tool_result only its call id."""
    names: dict[str, str] = {}
    for message in messages:
        content = message.get("content")
        for block in content if isinstance(content, list) else []:
            if block.get("type") == "tool_use":
                names[block["id"]] = block["name"]
    return names


def _part(block: dict, names: dict[str, str]) -> Any:
    from google.genai import types

    kind = block.get("type")
    if kind == "text":
        return types.Part(text=block["text"])
    if kind == "tool_use":
        return types.Part(
            function_call=types.FunctionCall(
                id=block["id"], name=block["name"], args=block.get("input") or {}
            )
        )
    if kind == "tool_result":
        key = "error" if block.get("is_error") else "output"
        call_id = block.get("tool_use_id") or ""
        return types.Part(
            function_response=types.FunctionResponse(
                id=call_id, name=names.get(call_id, "tool"), response={key: block.get("content", "")}
            )
        )
    return None  # other block types are not used by the agent loop


def to_contents(messages: list[dict]) -> list[Any]:
    """Provider-neutral messages (user | assistant, text or blocks) -> Gemini contents (user | model)."""
    from google.genai import types

    names = _tool_names(messages)
    contents = []
    for message in messages:
        content = message.get("content")
        blocks = [{"type": "text", "text": content}] if isinstance(content, str) else content or []
        parts = [p for p in (_part(b, names) for b in blocks) if p is not None]
        if parts:
            role = "model" if message.get("role") == "assistant" else "user"
            contents.append(types.Content(role=role, parts=parts))
    return contents


def _turn_blocks(response: Any) -> list[dict]:
    candidate = (response.candidates or [None])[0]
    parts = (candidate.content.parts if candidate and candidate.content else None) or []
    blocks: list[dict] = []
    for part in parts:
        if part.function_call is not None:
            call = part.function_call
            call_id = call.id or f"call_{uuid.uuid4().hex[:16]}"
            blocks.append(
                {"type": "tool_use", "id": call_id, "name": call.name, "input": dict(call.args or {})}
            )
        elif part.text and not part.thought:
            blocks.append({"type": "text", "text": part.text})
    return blocks


def _stop_reason(response: Any, blocks: list[dict]) -> str:
    """The agent loop's stop reasons: max_tokens (cut off), tool_use, or end_turn."""
    candidate = (response.candidates or [None])[0]
    finish = getattr(getattr(candidate, "finish_reason", None), "name", "") if candidate else ""
    if finish == "MAX_TOKENS":
        return "max_tokens"
    if any(b["type"] == "tool_use" for b in blocks):
        return "tool_use"
    return "end_turn"


class VertexProvider:
    """Non-streaming generate_content call to Gemini on Vertex AI; the client is created once per process."""

    def __init__(self, client: Any = None) -> None:
        self._client = client

    def call(
        self, *, model: str, system: str, messages: list[dict], tools: list[ToolSpec], max_tokens: int
    ) -> ModelTurn:
        from google.genai import types

        client = self._client or _shared_client()
        config = types.GenerateContentConfig(
            system_instruction=system or None,
            max_output_tokens=min(max_tokens, MAX_TOKENS_CAP),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            tools=[
                types.Tool(
                    function_declarations=[
                        types.FunctionDeclaration(
                            name=t.name, description=t.description, parameters_json_schema=t.input_schema
                        )
                        for t in tools
                    ]
                )
            ]
            if tools
            else None,
        )
        response = client.models.generate_content(model=model, contents=to_contents(messages), config=config)
        blocks = _turn_blocks(response)
        usage = response.usage_metadata
        # Thinking tokens are billed as output, so spend counts them with the visible answer.
        output_tokens = (
            ((usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0)) if usage else 0
        )
        return ModelTurn(
            content=blocks,
            stop_reason=_stop_reason(response, blocks),
            input_tokens=(usage.prompt_token_count or 0) if usage else 0,
            output_tokens=output_tokens,
            model=response.model_version or model,
        )


# --- fake ------------------------------------------------------------------------------------------


def agent_id_of(system: str) -> str:
    first = system.split("\n", 1)[0].strip()
    if not first.startswith(AGENT_MARKER):
        raise LookupError("system prompt has no agent:<id> marker")
    return first[len(AGENT_MARKER) :].strip()


def inputs_of(messages: list[dict]) -> dict:
    """The JSON inputs block of the first user message (see agent.build_user_message)."""
    text = next((m["content"] for m in messages if m["role"] == "user" and isinstance(m["content"], str)), "")
    block = text[text.find(INPUTS_HEADING) :] if INPUTS_HEADING in text else ""
    start, end = block.find("```json\n"), block.rfind("```")
    if start < 0 or end <= start:
        return {}
    return json.loads(block[start + len("```json\n") : end])


def _records(value: Any, key: str) -> list[dict]:
    """Accept either the connector's envelope ({"orders": [...]}) or a bare list."""
    if isinstance(value, dict):
        return list(value.get(key) or [])
    return list(value or [])


def _major(minor: int) -> str:
    sign = "-" if minor < 0 else ""
    return f"{sign}{abs(minor) // 100}.{abs(minor) % 100:02d}"


_ORDER_REF = re.compile(r"#\d+")
_ROUNDING_MINOR = 1
_PAIRING_WINDOW_DAYS = 2


def _orders(raw: Any) -> list[dict]:
    return [
        {
            "order_id": o["name"],
            "date": datetime.fromisoformat(o["created_at"]).astimezone(UTC).date().isoformat(),
            "amount_minor": int((Decimal(str(o["total_price"])) * 100).to_integral_value()),
            "currency": str(o["currency"]).upper(),
        }
        for o in _records(raw, "orders")
    ]


def _charges(raw: Any) -> list[dict]:
    out = []
    for c in _records(raw, "data"):
        ref = (c.get("metadata") or {}).get("order_id")
        if not ref:
            found = _ORDER_REF.search(c.get("description") or "")
            ref = found.group(0) if found else None
        out.append(
            {
                "charge_id": c["id"],
                "date": datetime.fromtimestamp(c["created"], UTC).date().isoformat(),
                "amount_minor": int(c["amount"]),
                "currency": str(c["currency"]).upper(),
                "ref": ref,
            }
        )
    return out


def _days_apart(a: str, b: str) -> int:
    return abs((datetime.fromisoformat(a) - datetime.fromisoformat(b)).days)


def _pair(orders: list[dict], charges: list[dict]) -> tuple[dict[str, dict], list[dict]]:
    """Pair orders with charges per the match-orders skill. Returns (order_id -> charge, duplicates)."""
    known = {o["order_id"] for o in orders}
    pairs: dict[str, dict] = {}
    duplicates: list[dict] = []
    for c in charges:
        if c["ref"] not in known:
            continue
        if c["ref"] in pairs:
            duplicates.append(c)
        else:
            pairs[c["ref"]] = c
    used = {c["charge_id"] for c in pairs.values()} | {c["charge_id"] for c in duplicates}
    for o in orders:
        if o["order_id"] in pairs:
            continue
        fits = [
            c
            for c in charges
            if c["charge_id"] not in used
            and c["currency"] == o["currency"]
            and abs(c["amount_minor"] - o["amount_minor"]) <= _ROUNDING_MINOR
            and _days_apart(c["date"], o["date"]) <= _PAIRING_WINDOW_DAYS
        ]
        if len(fits) == 1:
            pairs[o["order_id"]] = fits[0]
            used.add(fits[0]["charge_id"])
    return pairs, duplicates


def _mismatch(order: dict | None, charge: dict | None, kind: str, explanation: str) -> dict:
    base = order or charge
    paid = charge["amount_minor"] if charge else 0
    owed = order["amount_minor"] if order and kind != "duplicate" else 0
    return {
        "order_id": order["order_id"] if order else None,
        "charge_id": charge["charge_id"] if charge else None,
        "kind": kind,
        "date": base["date"],
        "amount_minor": base["amount_minor"],
        "amount_diff_minor": paid - owed,
        "currency": base["currency"],
        "explanation": explanation,
    }


def fake_match(inputs: dict) -> dict:
    """A deterministic finance-agent result computed from the orders and charges in the inputs."""
    orders, charges = _orders(inputs.get("orders")), _charges(inputs.get("charges"))
    pairs, duplicates = _pair(orders, charges)
    matched, mismatches = [], []
    for o in orders:
        c = pairs.get(o["order_id"])
        if c is None:
            text = f"Order {o['order_id']} ({_major(o['amount_minor'])} {o['currency']}) has no payment."
            mismatches.append(_mismatch(o, None, "missing_payment", text))
        elif c["currency"] != o["currency"]:
            text = f"Charge {c['charge_id']} is in {c['currency']}, order {o['order_id']} in {o['currency']}."
            mismatches.append(_mismatch(o, c, "currency_mismatch", text))
        elif abs(c["amount_minor"] - o["amount_minor"]) > _ROUNDING_MINOR:
            diff = c["amount_minor"] - o["amount_minor"]
            text = (
                f"Charge {c['charge_id']} is {_major(abs(diff))} {o['currency']} "
                f"{'less' if diff < 0 else 'more'} than order {o['order_id']}; this merchant reports gross "
                "amounts, so a card fee does not explain it."
            )
            mismatches.append(_mismatch(o, c, "amount_mismatch", text))
        else:
            matched.append({k: o[k] for k in ("order_id", "date", "amount_minor", "currency")})
            matched[-1]["charge_id"] = c["charge_id"]
    paired = {c["charge_id"] for c in pairs.values()} | {c["charge_id"] for c in duplicates}
    for c in duplicates:
        text = f"Charge {c['charge_id']} is a second payment for order {c['ref']}."
        mismatches.append(_mismatch(None, c, "duplicate", text) | {"order_id": c["ref"]})
    for c in charges:
        if c["charge_id"] not in paired:
            text = f"Charge {c['charge_id']} ({_major(c['amount_minor'])} {c['currency']}) matches no order."
            mismatches.append(_mismatch(None, c, "missing_order", text))
    currency = (orders or charges or [{"currency": "USD"}])[0]["currency"]
    return {
        "matched": sorted(matched, key=lambda m: (m["date"], m["order_id"])),
        "mismatches": sorted(mismatches, key=lambda m: (m["date"], m["order_id"] or m["charge_id"])),
        "totals": {
            "orders_count": len(orders),
            "charges_count": len(charges),
            "matched_count": len(matched),
            "mismatch_count": len(mismatches),
            "orders_total_minor": sum(o["amount_minor"] for o in orders),
            "charges_total_minor": sum(c["amount_minor"] for c in charges),
            "currency": currency,
        },
    }


def _review_status(resolution: dict | None) -> str:
    if resolution is None:
        return "unreviewed"
    return "open" if resolution.get("resolution") == "open" else "resolved"


def fake_report(inputs: dict) -> dict:
    """A deterministic ops-agent report built per the write-report skill."""
    match = inputs.get("match") or {}
    review = inputs.get("review") or {}
    resolutions = {r["order_id"]: r for r in review.get("resolutions") or [] if r.get("order_id")}
    totals = match.get("totals") or {}
    currency = totals.get("currency", "USD")
    rows = [
        [m["date"], m["order_id"], "matched", _major(m["amount_minor"]), "matched", ""]
        for m in match.get("matched") or []
    ]
    open_ids: list[str] = []
    resolved = 0
    for mm in sorted(match.get("mismatches") or [], key=lambda m: m["date"]):
        ident = mm["order_id"] or mm["charge_id"]
        resolution = resolutions.get(ident)
        status = _review_status(resolution)
        if status == "resolved":
            resolved += 1
        else:
            open_ids.append(ident)
        note = (resolution or {}).get("note") or mm["explanation"]
        rows.append([mm["date"], ident, mm["kind"], _major(mm["amount_minor"]), status, note])
    net = sum(mm["amount_diff_minor"] for mm in match.get("mismatches") or [])
    still_open = f"Still open: {', '.join(open_ids)}." if open_ids else "Nothing is left open."
    summary = (
        f"Checked {totals.get('orders_count', 0)} orders: {totals.get('matched_count', 0)} matched and "
        f"{totals.get('mismatch_count', 0)} did not, {resolved} of them resolved by a reviewer. "
        f"Net difference {_major(net)} {currency}. {still_open}"
    )
    return {
        "summary": summary,
        "rows": rows,
        "totals": {
            "orders_count": totals.get("orders_count", 0),
            "matched_count": totals.get("matched_count", 0),
            "mismatch_count": totals.get("mismatch_count", 0),
            "net_difference_minor": net,
            "currency": currency,
        },
    }


# --- seed packs: collections, refunds and the shared writer ------------------------------------------------

_GENTLE_MAX_DAYS = 14  # overdue 1-14 days: gentle; 15-44: firm; 45 or more: final notice
_FIRM_MAX_DAYS = 44
_OPENED_OR_USED = re.compile(r"\b(?:opened|used)\b", re.IGNORECASE)  # the partial refund rule
_AMOUNT = re.compile(r"\$\s?(\d[\d,]*(?:\.\d{1,2})?)")
_EMAIL = re.compile(r"[^<>\s]+@[^<>\s]+")
_MS_TIMESTAMP_MIN = 10**11  # numeric timestamps above this are milliseconds
DEFAULT_SIGNATURE = "Accounts team"
SIGN_OFF = "Kind regards,\nAccounts team"
_STAGES = {"gentle": "gentle", "firm": "firm", "final": "final notice"}
_BANDS = {"gentle": "1 to 14", "firm": "15 to 44", "final": "45 or more"}
_REFUND_FLAGS = {
    "approve": "Proposed: approve",
    "partial": "Proposed: partial 50%",
    "decline": "Proposed: decline",
}


def _money(minor: int, currency: str) -> str:
    """Minor units for people: 125000, "USD" -> "1,250.00 USD"."""
    sign = "-" if minor < 0 else ""
    return f"{sign}{abs(minor) // 100:,}.{abs(minor) % 100:02d} {currency}"


def _instant(value: Any) -> datetime:
    """A UTC datetime from a Unix timestamp (seconds or milliseconds) or an ISO 8601 string."""
    if isinstance(value, int | float) or str(value).isdigit():
        seconds = int(value)
        seconds = seconds // 1000 if seconds > _MS_TIMESTAMP_MIN else seconds
        return datetime.fromtimestamp(seconds, UTC)
    return datetime.fromisoformat(str(value)).astimezone(UTC)


def _day(value: Any) -> date:
    """The UTC calendar day of a Unix timestamp (seconds or milliseconds) or an ISO 8601 string."""
    return _instant(value).date()


def _stage(days: int) -> str:
    if days <= _GENTLE_MAX_DAYS:
        return "gentle"
    return "firm" if days <= _FIRM_MAX_DAYS else "final"


def _overdue_invoice(inv: dict, as_of: date) -> tuple[dict, dict] | None:
    """(message, review item) for an invoice overdue on `as_of`, else None."""
    if inv.get("status") != "open" or not inv.get("due_date"):
        return None
    due = _day(inv["due_date"])
    days = (as_of - due).days
    if days < 1:
        return None
    stage, number = _stage(days), str(inv.get("number") or inv["id"])
    currency, amount = str(inv.get("currency") or "usd").upper(), int(inv.get("amount_due") or 0)
    message = {
        "to": str(inv["customer_email"]),
        "about": f"Invoice {number} is {days} days overdue",
        "ref": number,
        "facts": [
            f"Invoice number: {number}",
            f"Amount due: {_money(amount, currency)}",
            f"Due date: {due.isoformat()}",
            f"Stage: {_STAGES[stage]} ({days} days overdue)",
        ],
    }
    item = {
        "ref": number,
        "date": due.isoformat(),
        "amount_minor": amount,
        "currency": currency,
        "flag": f"Overdue {days} days ({_STAGES[stage]})",
        "note": f"{days} days past due, which is in the {_BANDS[stage]} day band, so the reminder is "
        f"{_STAGES[stage]}.",
    }
    return message, item


def fake_collections(inputs: dict) -> dict:
    """A deterministic collections-agent plan per the stage-overdue skill."""
    as_of = date.fromisoformat(str(inputs.get("as_of")))
    invoices = _records(inputs.get("invoices"), "data")
    planned = [p for p in (_overdue_invoice(inv, as_of) for inv in invoices) if p is not None]
    messages, items = [m for m, _ in planned], [i for _, i in planned]
    if not planned:
        summary = f"Checked {len(invoices)} invoices as of {as_of}: none is overdue."
    else:
        counts = {
            s: sum(1 for i in items if i["flag"].endswith(f"({label})")) for s, label in _STAGES.items()
        }
        summary = (
            f"Checked {len(invoices)} invoices as of {as_of}: {len(planned)} are overdue "
            f"({counts['gentle']} gentle, {counts['firm']} firm, {counts['final']} final notice)."
        )
    return {"summary": summary, "messages": messages, "review_items": items}


def _refund_request(msg: dict) -> dict:
    preview = msg.get("preview") or {}
    text = f"{msg.get('subject') or ''} {msg.get('messageText') or preview.get('body') or ''}"
    ref, amount = _ORDER_REF.search(text), _AMOUNT.search(text)
    sender = _EMAIL.search(str(msg.get("sender") or ""))
    asked = int((Decimal(amount.group(1).replace(",", "")) * 100).to_integral_value()) if amount else None
    return {
        "thread_id": str(msg.get("threadId") or msg.get("messageId")),
        "from": sender.group(0) if sender else str(msg.get("sender") or ""),
        "ref": ref.group(0) if ref else None,
        "asked_minor": asked,
        "opened_or_used": bool(_OPENED_OR_USED.search(text)),
        "at": _instant(msg["messageTimestamp"]),
    }


def _refunded_orders(orders: dict[str, dict], raw_charges: Any) -> set[str]:
    """Order names whose payment is already refunded, per the find-order skill."""
    refunded = {name for name, o in orders.items() if o.get("financial_status") == "refunded"}
    for charge, c in zip(_records(raw_charges, "data"), _charges(raw_charges), strict=True):
        amount = int(charge.get("amount") or 0)
        if c["ref"] and (charge.get("refunded") or int(charge.get("amount_refunded") or 0) >= amount > 0):
            refunded.add(c["ref"])
    return refunded


def _refund_decision(
    request: dict, order: dict | None, repeats: str | None, refunded: bool
) -> tuple[str, int, int, str, str]:
    """(recommendation, requested minor, proposed minor, currency, reason) per the refund policy."""
    if order is None:
        named = f"No order {request['ref']} was found" if request["ref"] else "The request names no order"
        return "decline", request["asked_minor"] or 0, 0, "USD", f"{named}, so the request is declined."
    total = int((Decimal(str(order["total_price"])) * 100).to_integral_value())
    requested = request["asked_minor"] or total
    capped, currency = min(requested, total), str(order["currency"]).upper()
    if repeats:
        reason = f"This repeats the earlier request {repeats} for order {order['name']}, so it is declined."
        return "decline", requested, 0, currency, reason
    if refunded:
        reason = f"The payment for order {order['name']} is already refunded, so the request is declined."
        return "decline", requested, 0, currency, reason
    if request["opened_or_used"]:
        reason = "The customer says the item was opened or used, so the refund is 50% of the amount asked."
        return "partial", requested, capped // 2, currency, reason
    reason = f"Order {order['name']} is found, paid and not refunded, so the refund is approved in full."
    return "approve", requested, capped, currency, reason


def _refund_triage(request: dict, decision: tuple, charge_id: str | None) -> tuple[dict, dict, dict]:
    """(case, reply message, review item) for one refund request."""
    recommendation, requested, amount, currency, reason = decision
    case = {
        "thread_id": request["thread_id"],
        "from": request["from"],
        "order_id": request["order"]["name"] if request["order"] else None,
        "charge_id": charge_id,
        "requested_minor": requested,
        "currency": currency,
        "recommendation": recommendation,
        "amount_minor": amount,
        "reason": reason,
    }
    proposal = {
        "approve": f"approve the full refund of {_money(amount, currency)}",
        "partial": f"refund 50% ({_money(amount, currency)})",
        "decline": "decline the refund",
    }[recommendation]
    about = "Your refund request" + (f" for order {request['ref']}" if request["ref"] else "")
    message = {
        "to": request["from"],
        "about": about,
        "facts": [
            f"Order number: {request['ref'] or 'not given'}",
            f"Requested refund: {_money(requested, currency)}",
            f"Proposed decision: {proposal}. {reason}",
            "This decision is proposed and a member of our team will confirm it. "
            "No refund has been issued yet.",
        ],
        "ref": request["review_ref"],  # pairs the reply with its review item, so a reviewer's note reaches it
    }
    item = {
        "ref": request["review_ref"],
        "date": request["at"].date().isoformat(),
        "amount_minor": requested,
        "currency": currency,
        "flag": _REFUND_FLAGS[recommendation],
        "note": reason,
    }
    if charge_id:
        item["counterpart_ref"] = charge_id
    return case, message, item


def fake_refunds(inputs: dict) -> dict:
    """A deterministic refunds-agent triage per the find-order and apply-refund-policy skills."""
    orders = {str(o["name"]): o for o in _records(inputs.get("orders"), "orders")}
    charges = {c["ref"]: c["charge_id"] for c in reversed(_charges(inputs.get("charges"))) if c["ref"]}
    refunded = _refunded_orders(orders, inputs.get("charges"))
    threads = _records(inputs.get("threads"), "messages")
    requests = sorted((_refund_request(m) for m in threads), key=lambda r: r["at"])  # oldest first
    first_request: dict[str, str] = {}  # order name -> the thread that asked first
    triaged = []
    for r in requests:
        order = orders.get(r["ref"] or "")
        repeats = first_request.get(order["name"]) if order else None
        if order and not repeats:
            first_request[order["name"]] = r["thread_id"]
        own_ref = r["ref"] if r["ref"] and not repeats else r["thread_id"]
        request = r | {"order": order, "review_ref": own_ref}
        decision = _refund_decision(r, order, repeats, bool(order) and order["name"] in refunded)
        triaged.append(_refund_triage(request, decision, charges.get(order["name"]) if order else None))
    cases = [c for c, _, _ in triaged]
    count = {r: sum(1 for c in cases if c["recommendation"] == r) for r in _REFUND_FLAGS}
    summary = (
        f"Triaged {len(cases)} refund requests: {count['approve']} proposed for approval, {count['partial']} "
        f"for a partial refund and {count['decline']} for decline. No refund has been issued."
    )
    return {
        "summary": summary,
        "cases": cases,
        "messages": [m for _, m, _ in triaged],
        "review_items": [i for _, _, i in triaged],
    }


def fake_writer(inputs: dict) -> dict:
    """A deterministic writer-agent result per the write-drafts skill: one draft per item."""
    drafts = []
    sign_off = f"Kind regards,\n{str(inputs.get('sign_off') or DEFAULT_SIGNATURE)}"
    for item in inputs.get("items") or []:
        facts = [str(f) for f in item.get("facts") or []]
        sentences = " ".join(f if f.endswith((".", "!", "?")) else f"{f}." for f in facts)
        first = facts[0] if facts else ""
        ref = item.get("ref") or (first.split(": ", 1)[1] if ": " in first else str(item["about"]))
        body = f"Hello,\n\n{sentences}\n\nPlease reply to this email if you have any questions.\n\n{sign_off}"
        drafts.append(
            {
                "to": str(item["to"]),
                "subject": str(item["about"])[:150],
                "body": body[:4000],
                "ref": str(ref),
            }
        )
    return {"drafts": drafts}


# --- team agents (built in the Studio) ----------------------------------------------------------------------

TEAM_RESULT_TITLE = "Agent result"  # the title of shared/agent-result, which every team agent submits
FAKE_TEAM_DATE = "2026-10-13"  # a review item's date when its record has none
FAKE_TEAM_LIMIT = 3  # records a team agent works on under the fake model
_SETTLED = {"paid", "void", "closed", "uncollectible", "refunded"}
_LIST_KEYS = ("data", "orders", "messages", "items", "records")
_CURRENCY = "USD"
_CURRENCY_CODE = re.compile(r"^[A-Za-z]{3}$")
_FALLBACK_EMAIL = "customer@example.com"


def _first_records(inputs: dict) -> list[dict]:
    """The first list of records among the inputs (by input name), a connector's envelope unwrapped."""
    for _, value in sorted(inputs.items()):
        if isinstance(value, dict):
            value = next(
                (value[k] for k in _LIST_KEYS if isinstance(value.get(k), list) and value.get(k)), None
            )
        if isinstance(value, list) and value and all(isinstance(r, dict) for r in value):
            return value
    return []


def _email(record: dict) -> str:
    for key in ("customer_email", "email", "sender", "from", "to"):
        found = _EMAIL.search(str(record.get(key) or ""))
        if found:
            return found.group(0)
    return _FALLBACK_EMAIL


def _record_ref(record: dict, index: int) -> str:
    return str(record.get("number") or record.get("name") or record.get("id") or f"item-{index + 1}")


def _record_minor(record: dict) -> int:
    for key in ("amount_due", "amount"):
        value = record.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    if record.get("total_price") is not None:
        try:
            return int((Decimal(str(record["total_price"])) * 100).to_integral_value())
        except InvalidOperation, ValueError:
            return 0
    return 0


def _record_currency(record: dict) -> str:
    code = str(record.get("currency") or "")
    return code.upper() if _CURRENCY_CODE.match(code) else _CURRENCY


def _record_day(record: dict) -> str:
    for key in ("due_date", "created", "created_at"):
        if record.get(key):
            try:
                return _day(record[key]).isoformat()
            except ValueError, TypeError, OverflowError:
                continue
    return FAKE_TEAM_DATE


def fake_team_agent(inputs: dict) -> dict:
    """A deterministic result for any team agent (shared/agent-result): one message and one review item for
    each of the first three open records in its inputs."""
    records = [r for r in _first_records(inputs) if str(r.get("status") or "").lower() not in _SETTLED]
    messages, items = [], []
    for i, record in enumerate(records[:FAKE_TEAM_LIMIT]):
        ref = _record_ref(record, i)
        messages.append(
            {"to": _email(record), "about": f"About {ref}", "facts": [f"Reference: {ref}."], "ref": ref}
        )
        items.append(
            {
                "ref": ref,
                "date": _record_day(record),
                "amount_minor": _record_minor(record),
                "currency": _record_currency(record),
                "flag": "Check before sending",
                "note": f"Drafted from record {ref}.",
            }
        )
    n = len(messages)
    summary = (
        f"Prepared {n} message{'s' if n != 1 else ''} from the inputs."
        if n
        else "Nothing to work on in the inputs."
    )
    return {"summary": summary, "messages": messages, "review_items": items}


def _submits(tools: list[ToolSpec], title: str) -> bool:
    """Whether the agent's submit tool takes the schema titled `title`."""
    return any(t.name == SUBMIT_TOOL and t.input_schema.get("title") == title for t in tools)


_DEFAULT_SCRIPT = {
    "finance-agent": fake_match,
    "ops-agent": fake_report,
    "collections-agent": fake_collections,
    "refunds-agent": fake_refunds,
    "writer-agent": fake_writer,
}


def _sample_pack_script(agent_id: str):
    from app.runtime import fakes  # lazy: the pack scripts import helpers, never this module at import time

    return fakes.agent_script(agent_id)


class FakeProvider:
    """Scripted provider. The turn returned is chosen by agent id (system prompt marker "agent:<id>") and by
    how many assistant turns the conversation already has, so it is stateless across activity calls.

    Without a script entry, the agents in _DEFAULT_SCRIPT (the reconciliation, overdue invoice and refund
    triage agents, and the shared writer) submit a deterministic result computed from their inputs, valid
    against their output schemas. Any other agent whose result is shared/agent-result (an agent an org built
    in the Studio) submits `fake_team_agent`'s result. Agents of the sample packs submit the script in
    app.runtime.fakes.
    """

    def __init__(self, script: dict[str, list[ModelTurn]] | None = None) -> None:
        self._script = dict(script or {})

    def call(
        self, *, model: str, system: str, messages: list[dict], tools: list[ToolSpec], max_tokens: int
    ) -> ModelTurn:
        agent_id = agent_id_of(system)
        turn_index = sum(1 for m in messages if m["role"] == "assistant")
        if agent_id in self._script:
            turns = self._script[agent_id]
            return turns[min(turn_index, len(turns) - 1)]
        if agent_id in _DEFAULT_SCRIPT:
            result = _DEFAULT_SCRIPT[agent_id](inputs_of(messages))
        elif (script := _sample_pack_script(agent_id)) is not None:
            result = script(inputs_of(messages))
        elif _submits(tools, TEAM_RESULT_TITLE):
            result = fake_team_agent(inputs_of(messages))
        else:
            raise LookupError(f"fake provider has no script for agent {agent_id!r}")
        block = {"type": "tool_use", "id": f"toolu_fake_{turn_index}", "name": SUBMIT_TOOL, "input": result}
        return ModelTurn(
            content=[block],
            stop_reason="tool_use",
            input_tokens=FAKE_INPUT_TOKENS,
            output_tokens=FAKE_OUTPUT_TOKENS,
            model=model,
        )
