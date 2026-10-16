"""Fake meeting-agent for the Meeting Follow-ups pack, following skills/plan-follow-ups.md."""

NO_AGREEMENT = "Please let me know if anything from the meeting needs a follow-up."


def _events(value: object) -> list[dict]:
    items = value.get("items") if isinstance(value, dict) else value
    return [e for e in items or [] if isinstance(e, dict)]


def _domain(email: object) -> str:
    return str(email).partition("@")[2].lower()


def _guests(event: dict) -> list[dict]:
    attendees = [a for a in event.get("attendees") or [] if isinstance(a, dict) and a.get("email")]
    own = next((a["email"] for a in attendees if a.get("self")), "")
    if not own:
        return []
    return [
        a
        for a in attendees
        if not a.get("self") and _domain(a["email"]) != _domain(own) and a.get("responseStatus") != "declined"
    ]


def _agreed(event: dict) -> list[str]:
    lines = (line.strip() for line in str(event.get("description") or "").splitlines())
    return [line for line in lines if line.startswith("Agreed:")]


def fake_meetings(inputs: dict) -> dict:
    day = str(inputs.get("day") or "")
    meetings, messages = [], []
    for event in _events(inputs.get("events")):
        title = str(event.get("summary") or "Meeting")[:200]
        start = event.get("start") or {}
        guests = _guests(event)
        if event.get("status") == "cancelled":
            follow, reason = False, "The meeting was cancelled."
        elif not guests:
            follow, reason = False, "Nobody outside your team took part."
        else:
            noun = "person" if len(guests) == 1 else "people"
            follow, reason = True, f"Follow up with {len(guests)} {noun} outside your team."
        event_id = str(event.get("id") or title)
        meetings.append(
            {
                "event_id": event_id,
                "title": title,
                "start": str(start.get("dateTime") or start.get("date") or ""),
                "follow_up": follow,
                "reason": reason,
            }
        )
        if not follow:
            continue
        for guest in guests:
            messages.append(
                {
                    "to": guest["email"],
                    "about": f"Follow-up: {title}"[:150],
                    "facts": [
                        f'Thank you for the meeting "{title}" on {day}.',
                        *(_agreed(event) or [NO_AGREEMENT]),
                    ],
                    "ref": f"{event_id}:{guest['email']}",
                }
            )
    read = "1 meeting" if len(meetings) == 1 else f"{len(meetings)} meetings"
    planned = "1 follow-up" if len(messages) == 1 else f"{len(messages)} follow-ups"
    summary = (
        f"Read {read} on {day} and planned {planned}."
        if messages
        else f"No meeting on {day} needs a follow-up."
    )
    return {"summary": summary, "meetings": meetings, "messages": messages}


AGENTS = {"meeting-agent": fake_meetings}
JEV: dict = {}
