---
name: spot-anomalies
description: Flag orders that look unusual and say why.
---

Look through the orders you read and flag only what the data shows:

- A total far above the others in the period (state the total and the typical range).
- An order with a payment status other than `paid`.
- An order that carries refunds.
- Two orders from the same email with the same total on the same day.
- A currency that differs from the rest of the period.

For each flag give the order name, what stands out, and the numbers behind it. Do not speculate about fraud or intent. If nothing stands out, say that nothing unusual was found.
