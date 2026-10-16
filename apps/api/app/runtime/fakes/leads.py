"""Fake lead-agent and decision-model answers for the Inbox Lead Tracker pack."""

import re

from app.runtime.fakes._shared import day, field, has_word, messages, sender

_ENQUIRY_WORDS = (
    "quote",
    "price",
    "prices",
    "pricing",
    "booking",
    "book",
    "workshops",
    "know more",
    "enquiry",
)
_AUTOMATED_SENDERS = ("news@", "billing@", "noreply", "no-reply", "offers@")
_BRACKETED = re.compile(r"\(([^()]{2,80})\)")
_ROW_FIELDS = ("received", "name", "company", "email", "request", "urgency", "thread_id")


def is_lead(state: str) -> dict:
    who = field(state, "From").lower()
    if any(s in who for s in _AUTOMATED_SENDERS):
        return {"type": "noul", "noul": 0.04}
    text = f"{field(state, 'Subject')} {field(state, 'Text')}"
    return {"type": "noul", "noul": 0.93 if has_word(text, *_ENQUIRY_WORDS) else 0.12}


def urgency(state: str) -> dict:
    text = f"{field(state, 'Subject')} {field(state, 'Text')}"
    if has_word(text, "today", "tomorrow", "urgent", "asap"):
        choice = "urgent"
    elif has_word(text, "this week", "next week"):
        choice = "soon"
    else:
        choice = "normal"
    return {"type": "choice", "choice": choice, "confidence": 0.8, "probabilities": {choice: 0.8}}


def _company(name: str, text: str) -> str:
    bracketed = _BRACKETED.search(text)
    if bracketed:
        return bracketed.group(1).strip()
    if name and f"{name}, " in text:
        return text.split(f"{name}, ", 1)[1].split(".")[0].strip()[:120] or "Not given"
    return "Not given"


def fake_leads(inputs: dict) -> dict:
    urgency_of = {
        str(i.get("ref")): ((i.get("answers") or {}).get("urgency") or {}).get("value", "normal")
        for i in inputs.get("screening") or []
        if isinstance(i, dict)
    }
    leads = []
    for email in messages(inputs.get("emails")):
        name, address = sender(email.get("sender"))
        text = str(email.get("messageText") or "")
        leads.append(
            {
                "thread_id": str(email.get("threadId") or email.get("messageId")),
                "received": day(email.get("messageTimestamp")),
                "name": (name or address.partition("@")[0])[:120],
                "company": _company(name, text),
                "email": address,
                "request": str(email.get("subject") or "Enquiry")[:200],
                "urgency": urgency_of.get(str(email.get("messageId")), "normal"),
            }
        )
    rows = [[lead[k] for k in _ROW_FIELDS] for lead in leads]
    urgent = sum(1 for lead in leads if lead["urgency"] == "urgent")
    noun = "lead" if len(leads) == 1 else "leads"
    summary = f"Found {len(leads)} {noun}, {urgent} urgent." if leads else "No leads were found."
    return {"summary": summary, "leads": leads, "rows": rows}


AGENTS = {"lead-agent": fake_leads}
JEV = {"is_lead": is_lead, "urgency": urgency}
