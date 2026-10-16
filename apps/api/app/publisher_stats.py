"""The publisher's numbers (sub-project D): installs, runs in the last 30 days and earnings per listing,
earnings by month (simulated payouts), and the ops overview's publishing numbers. Earnings are the publisher
share of fee lines; simulated, no money moves. Buyers' runs are counted here, never listed."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app import workspace
from app.models.common import Money
from app.models.publishing import PayoutMonth, PublisherEarnings

RUN_WINDOW_DAYS = 30
PAYOUT_MONTHS = 12


@dataclass(frozen=True)
class ListingNumbers:
    """One listing's installs by other workspaces, runs in the last 30 days and this month's earnings."""

    installs: int
    runs30d: int
    earnings_month_minor: int


def _window(now: datetime | None) -> dict:
    now = now or datetime.now(UTC)
    start = workspace._month_start(now)
    return {
        "since": now - timedelta(days=RUN_WINDOW_DAYS),
        "month": start,
        "next": workspace._next_month(start),
        "year": start.replace(year=start.year - 1),
    }


_NUMBERS = """
SELECT l.id,
  CASE WHEN l.kind = 'pack' THEN
    (SELECT count(*) FROM installations i
     WHERE i.pack_slug = l.definition_key AND i.org_id <> l.publisher_org_id)
  ELSE
    (SELECT count(DISTINCT o.owner_id) FROM definition_owners o
       JOIN LATERAL (SELECT v.body FROM definition_versions v WHERE v.kind = 'pack' AND v.key = o.key
                     ORDER BY v.version DESC LIMIT 1) p ON true
     WHERE o.kind = 'pack' AND o.owner_kind = 'org' AND o.owner_id <> l.publisher_org_id
       AND p.body -> 'agents' ? l.definition_key)
  END AS installs,
  (SELECT count(DISTINCT f.run_id) FROM fee_lines f
   WHERE f.listing_id = l.id AND f.created_at >= %(since)s) AS runs,
  (SELECT COALESCE(SUM(f.publisher_share_minor), 0) FROM fee_lines f WHERE f.listing_id = l.id
     AND f.created_at >= %(month)s AND f.created_at < %(next)s) AS earned
FROM listings l WHERE l.publisher_org_id = %(org)s
"""


def listing_numbers(conn, publisher_org_id: str, now: datetime | None = None) -> dict[str, ListingNumbers]:
    """The numbers of each listing the org publishes, by listing id; other workspaces only."""
    rows = conn.execute(_NUMBERS, {**_window(now), "org": publisher_org_id}).fetchall()
    return {r["id"]: ListingNumbers(int(r["installs"]), int(r["runs"]), int(r["earned"])) for r in rows}


def earnings(conn, org_id: str, now: datetime | None = None) -> PublisherEarnings:
    """The org's publisher share this month (UTC) and its simulated payouts for the 12 months before."""
    w = _window(now)
    month = conn.execute(
        "SELECT COALESCE(SUM(publisher_share_minor), 0) AS n FROM fee_lines WHERE publisher_org_id = %(org)s "
        "AND created_at >= %(month)s AND created_at < %(next)s",
        {**w, "org": org_id},
    ).fetchone()["n"]
    rows = conn.execute(
        "SELECT to_char(date_trunc('month', created_at AT TIME ZONE 'UTC'), 'YYYY-MM') AS month, "
        "SUM(publisher_share_minor) AS amount FROM fee_lines WHERE publisher_org_id = %(org)s "
        "AND created_at >= %(year)s AND created_at < %(month)s GROUP BY 1 ORDER BY 1 DESC LIMIT %(limit)s",
        {**w, "org": org_id, "limit": PAYOUT_MONTHS},
    ).fetchall()
    return PublisherEarnings(
        month=Money(amount_minor=int(month)),
        payouts=[PayoutMonth(month=r["month"], amount=Money(amount_minor=int(r["amount"]))) for r in rows],
    )


def ops_numbers(conn, now: datetime) -> tuple[int, int]:
    """(listing versions waiting for review, those whose checks just passed included; every publisher's share
    of fees this calendar month)."""
    w = _window(now)
    # A checking version whose sandbox run completed is in review already; it only waits to be settled.
    in_review = conn.execute(
        "SELECT count(*) AS n FROM listing_versions v LEFT JOIN runs r ON r.id = v.check_run_id "
        "WHERE v.status = 'in_review' OR (v.status = 'checking' AND r.status = 'COMPLETED')"
    ).fetchone()["n"]
    earned = conn.execute(
        "SELECT COALESCE(SUM(publisher_share_minor), 0) AS n FROM fee_lines "
        "WHERE created_at >= %(month)s AND created_at < %(next)s",
        w,
    ).fetchone()["n"]
    return int(in_review), int(earned)
