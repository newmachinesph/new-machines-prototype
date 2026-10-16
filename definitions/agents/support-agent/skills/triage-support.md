---
name: triage-support
description: Make one case per customer email, plan its reply and say which cases need a person.
---

`emails` holds the customer emails. `categories` holds one item per email the decision model sorted, `{ref, answers}`, where `ref` is the email's `messageId` and `answers.support_category.value` is `question`, `complaint`, `refund` or `spam`. `screened` is true when the decision model sorted the emails.

For each email, in order:

1. Category: when `screened`, the category from `categories` for the same `ref`; otherwise decide it yourself from the subject and text (refund words such as "refund" or "money back"; complaint words such as "disappointed", "damaged", "late", "broken"; marketing such as "unsubscribe" or "% off" is spam; anything else is a question). Leave spam out entirely.
2. Case: `thread_id`, `received` (date part of `messageTimestamp`), `from` (the sender's address), `subject`, `category`, and `needs_person`: true for a complaint or a refund, and true for every case when `screened` is false.
3. Message: `to` is the sender's address, `about` is `Re: <subject>`, `ref` is the `messageId`, and `facts` follow the support policies:
   - question: `Thank you for your question.`, `A member of our team will reply with a full answer within one working day.`, `Our support hours are Monday to Friday, 9:00 to 17:00.`
   - complaint: `We are sorry to hear about your experience.`, `A member of our team will look into it and reply within one working day.`
   - refund: `We have received your refund request.`, `A member of our team will check your order and reply within one working day.`, `No refund has been issued yet.`
4. Review item, for a case that needs a person: `ref` is the `messageId`, `date` is `received`, `amount_minor` is the amount the customer names in cents (0 when none), `currency` `USD`, `flag` is `Complaint`, `Refund request` or `Question`, and `note` says in one sentence why a person checks it: `A complaint needs a person's reply.`, `A refund needs a person to check the order.`, or, when not `screened`, `Sorted without the decision model; check the category.`
5. Row: `[received, from, subject, category, "yes" or "no" for needs_person, thread_id]`.

Never include email addresses, phone numbers or customer message text in a `note` or `flag`.
