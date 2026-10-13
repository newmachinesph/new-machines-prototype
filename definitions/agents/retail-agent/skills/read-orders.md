---
name: read-orders
description: Fetch the orders for a date range with the store tool.
---

Call `shopify.list_orders` with the period you were asked about.

- Pass `created_at_min` and `created_at_max` as ISO 8601 timestamps. Use `T00:00:00Z` for the first day and `T23:59:59Z` for the last day.
- Pass `status` as `any` so that cancelled and closed orders are included.
- Pass `limit` as `250`.
- The result is an object with an `orders` array. Order totals are decimal strings in major units; keep the currency with every total.

If `orders` is empty, report that no orders were found for the period. Do not fill the gap with assumptions.
