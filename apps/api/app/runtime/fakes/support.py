"""Fake support-agent and decision-model answer for the Support Inbox Triage pack, following
skills/triage-support.md."""

import re

from app.runtime.fakes._shared import day, field, has_word, messages, money_minor, sender

_REFUND = ("refund", "money back")
_COMPLAINT = ("disappointed", "damaged", "late", "broken", "unhappy", "complaint")
_SPAM = ("unsubscribe", "offers", "deals", "savings")
_AMOUNT = re.compile(r"\$\s?(\d[\d,]*(?:\.\d{1,2})?)")
FACTS = {
    "question": [
        "Thank you for your question.",
        "A member of our team will reply with a full answer within one working day.",
        "Our support hours are Monday to Friday, 9:00 to 17:00.",
    ],
    "complaint": [
        "We are sorry to hear about your experience.",
        "A member of our team will look into it and reply within one working day.",
    ],
    "refund": [
        "We have received your refund request.",
        "A member of our team will check your order and reply within one working day.",
        "No refund has been issued yet.",
    ],
}
FLAGS = {"question": "Question", "complaint": "Complaint", "refund": "Refund request"}
NOTES = {
    "complaint": "A complaint needs a person's reply.",
    "refund": "A refund needs a person to check the order.",
}
UNSCREENED_NOTE = "Sorted without the decision model; check the category."


def _category(who: str, subject: str, text: str) -> str:
    words = f"{subject} {text}"
    if has_word(words, *_SPAM) or any(s in who.lower() for s in ("offers@", "news@", "noreply")):
        return "spam"
    if has_word(words, *_REFUND):
        return "refund"
    if has_word(words, *_COMPLAINT):
        return "complaint"
    return "question"


def support_category(state: str) -> dict:
    choice = _category(field(state, "From"), field(state, "Subject"), field(state, "Text"))
    return {"type": "choice", "choice": choice, "confidence": 0.85, "probabilities": {choice: 0.85}}


def _amount(text: str) -> int:
    found = _AMOUNT.search(text)
    return (money_minor(found.group(1)) or 0) if found else 0


def fake_support(inputs: dict) -> dict:
    screened = inputs.get("screened") is True
    sorted_as = {
        str(i.get("ref")): ((i.get("answers") or {}).get("support_category") or {}).get("value")
        for i in inputs.get("categories") or []
        if isinstance(i, dict)
    }
    cases, outgoing, review_items, rows = [], [], [], []
    for email in messages(inputs.get("emails")):
        ref = str(email.get("messageId"))
        _, address = sender(email.get("sender"))
        subject = str(email.get("subject") or "Your email")[:200]
        text = str(email.get("messageText") or "")
        category = (
            sorted_as.get(ref) if screened else _category(str(email.get("sender") or ""), subject, text)
        )
        if category not in FACTS:
            continue  # spam, or no category: no reply and no case
        needs_person = category != "question" or not screened
        received = day(email.get("messageTimestamp"))
        cases.append(
            {
                "thread_id": str(email.get("threadId") or ref),
                "received": received,
                "from": address,
                "subject": subject,
                "category": category,
                "needs_person": needs_person,
            }
        )
        outgoing.append(
            {"to": address, "about": f"Re: {subject}"[:150], "facts": list(FACTS[category]), "ref": ref}
        )
        rows.append(
            [received, address, subject, category, "yes" if needs_person else "no", cases[-1]["thread_id"]]
        )
        if needs_person:
            review_items.append(
                {
                    "ref": ref,
                    "date": received,
                    "amount_minor": _amount(text),
                    "currency": "USD",
                    "flag": FLAGS[category],
                    "note": NOTES.get(category, UNSCREENED_NOTE) if screened else UNSCREENED_NOTE,
                }
            )
    summary = "No customer email needs an answer."
    if cases:
        made = (
            "1 customer email became a case"
            if len(cases) == 1
            else f"{len(cases)} customer emails became cases"
        )
        need = "1 needs a person" if len(review_items) == 1 else f"{len(review_items)} need a person"
        summary = f"{made}; {need}."
    return {
        "summary": summary,
        "cases": cases,
        "messages": outgoing,
        "review_items": review_items,
        "rows": rows,
    }


AGENTS = {"support-agent": fake_support}
JEV = {"support_category": support_category}
