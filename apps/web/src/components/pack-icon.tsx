import {
  Boxes,
  CalendarCheck,
  Inbox,
  Languages,
  LifeBuoy,
  Mail,
  ReceiptText,
  RotateCcw,
  Scale,
  ShieldAlert,
  Truck,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/cn";

const ICONS: Record<string, LucideIcon> = {
  "order-payment-reconciliation": Scale,
  "overdue-invoice-follow-up": Mail,
  "refund-triage": RotateCcw,
  "weekly-inventory-report": Boxes,
  "shipping-exceptions": Truck,
  "chargeback-evidence": ShieldAlert,
  "catalog-localization-en-ja": Languages,
  "inbox-lead-tracker": Inbox,
  "support-inbox-triage": LifeBuoy,
  "weekly-expense-check": ReceiptText,
  "meeting-follow-ups": CalendarCheck,
};

export function PackIcon({ slug, className }: { slug: string; className?: string }) {
  const Icon = ICONS[slug] ?? Boxes;
  return (
    <span
      className={cn(
        "grid size-9 shrink-0 place-items-center rounded-full border border-rule bg-paper text-ink",
        className,
      )}
      aria-hidden
    >
      <Icon className="size-4" strokeWidth={1.75} />
    </span>
  );
}
