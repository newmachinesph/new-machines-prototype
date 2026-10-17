"use client";

// Styled wrappers over Base UI primitives. Base UI owns behaviour (focus, keyboard, ARIA);
// these only add the New Machines look so every page uses the same parts.

import { AlertDialog } from "@base-ui/react/alert-dialog";
import { Checkbox as BaseCheckbox } from "@base-ui/react/checkbox";
import { Dialog } from "@base-ui/react/dialog";
import { Menu as BaseMenu } from "@base-ui/react/menu";
import { Radio } from "@base-ui/react/radio";
import { RadioGroup } from "@base-ui/react/radio-group";
import { Select as BaseSelect } from "@base-ui/react/select";
import { Toast } from "@base-ui/react/toast";
import { Toggle } from "@base-ui/react/toggle";
import { ToggleGroup } from "@base-ui/react/toggle-group";
import { Tooltip as BaseTooltip } from "@base-ui/react/tooltip";
import { Check, ChevronsUpDown, X } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useCallback, type ComponentProps, type ReactElement, type ReactNode } from "react";
import { cn } from "@/lib/cn";
import { Button } from "./ui";

const POPUP =
  "rounded-[10px] border border-rule bg-paper shadow-[0_8px_28px_rgb(17_17_17/0.12)] outline-none transition-[opacity,transform] duration-150 data-[ending-style]:opacity-0 data-[starting-style]:opacity-0 data-[starting-style]:scale-[0.98] data-[ending-style]:scale-[0.98]";
const ITEM =
  "flex w-full cursor-default select-none items-center gap-2.5 rounded-md px-2.5 py-2 text-left text-sm text-ink outline-none data-[highlighted]:bg-grey-100 data-[disabled]:opacity-45";

/* ── Providers ── */

export function UiProviders({ children }: { children: ReactNode }) {
  return (
    <Toast.Provider timeout={5000} limit={3}>
      <BaseTooltip.Provider delay={300}>
        {children}
        <ToastRegion />
      </BaseTooltip.Provider>
    </Toast.Provider>
  );
}

/* ── Toasts: confirm what an action did, in the same words as the action ── */

type ToastTone = "done" | "sim" | "blocked";
const TOAST_TONE: Record<ToastTone, string> = { done: "bg-ink", sim: "bg-sim", blocked: "bg-blocked" };

function ToastRegion() {
  const t = useTranslations("common");
  const { toasts } = Toast.useToastManager();
  return (
    <Toast.Portal>
      <Toast.Viewport
        aria-label={t("notifications")}
        className="fixed right-4 bottom-4 z-[60] flex w-[min(380px,calc(100vw-2rem))] flex-col gap-2 outline-none"
      >
        {toasts.map((toast) => (
          <Toast.Root
            key={toast.id}
            toast={toast}
            swipeDirection={["right", "down"]}
            className={cn(POPUP, "relative flex gap-3 py-3 pr-9 pl-3.5")}
          >
            <span
              className={cn(
                "mt-1.5 size-2 shrink-0 rounded-full",
                TOAST_TONE[(toast.type as ToastTone) ?? "done"] ?? "bg-ink",
              )}
              aria-hidden
            />
            <div className="min-w-0">
              <Toast.Title className="text-sm font-medium" />
              <Toast.Description className="mt-0.5 text-[13px] leading-snug text-grey-700" />
            </div>
            <Toast.Close
              aria-label={t("dismiss")}
              className="absolute top-2.5 right-2.5 grid size-6 place-items-center rounded text-grey-500 hover:bg-grey-100 hover:text-ink"
            >
              <X className="size-3.5" aria-hidden />
            </Toast.Close>
          </Toast.Root>
        ))}
      </Toast.Viewport>
    </Toast.Portal>
  );
}

export function useToast() {
  const { add } = Toast.useToastManager();
  return useCallback(
    (title: string, description?: string, tone: ToastTone = "done") => add({ title, description, type: tone }),
    [add],
  );
}

/* ── Tooltip ── */

export function Tooltip({
  label,
  children,
  side = "top",
}: {
  label: ReactNode;
  children: ReactElement;
  side?: "top" | "bottom" | "left" | "right";
}) {
  return (
    <BaseTooltip.Root>
      <BaseTooltip.Trigger render={children} />
      <BaseTooltip.Portal>
        <BaseTooltip.Positioner side={side} sideOffset={6} className="z-[70]">
          <BaseTooltip.Popup className="max-w-[280px] rounded-md bg-ink px-2.5 py-1.5 text-xs leading-snug text-paper shadow-md transition-opacity duration-100 data-[ending-style]:opacity-0 data-[starting-style]:opacity-0">
            {label}
          </BaseTooltip.Popup>
        </BaseTooltip.Positioner>
      </BaseTooltip.Portal>
    </BaseTooltip.Root>
  );
}

/* ── Menu ── */

export const MenuRoot = BaseMenu.Root;
export const MenuTrigger = BaseMenu.Trigger;

export function MenuPopup({
  children,
  align = "end",
  side = "bottom",
  className,
}: {
  children: ReactNode;
  align?: "start" | "end" | "center";
  /** Where the menu opens; a trigger at the bottom of the window opens upward. Flips when there is no room. */
  side?: "top" | "bottom";
  className?: string;
}) {
  return (
    <BaseMenu.Portal>
      <BaseMenu.Positioner align={align} side={side} sideOffset={6} className="z-50">
        <BaseMenu.Popup className={cn(POPUP, "min-w-56 p-1.5", className)}>{children}</BaseMenu.Popup>
      </BaseMenu.Positioner>
    </BaseMenu.Portal>
  );
}

export function MenuItem({ className, ...rest }: ComponentProps<typeof BaseMenu.Item>) {
  return <BaseMenu.Item className={cn(ITEM, className)} {...rest} />;
}

export function MenuLink({ href, children, className }: { href: string; children: ReactNode; className?: string }) {
  return (
    <BaseMenu.LinkItem closeOnClick render={<Link href={href} />} className={cn(ITEM, className)}>
      {children}
    </BaseMenu.LinkItem>
  );
}

const MENU_LABEL = "px-2.5 pt-1 pb-1.5 text-xs text-muted";

export function MenuLabel({ children }: { children: ReactNode }) {
  return <div className={MENU_LABEL}>{children}</div>;
}

/** A named set of items: role "group", labelled by its MenuGroupLabel, so assistive technology reads the heading. */
export const MenuGroup = BaseMenu.Group;

export function MenuGroupLabel({ children }: { children: ReactNode }) {
  return <BaseMenu.GroupLabel className={MENU_LABEL}>{children}</BaseMenu.GroupLabel>;
}

export function MenuSeparator() {
  return <BaseMenu.Separator className="my-1.5 h-px bg-rule" />;
}

/* ── Select ── */

export function Select<V extends string>({
  value,
  onValueChange,
  items,
  label,
  className,
  id,
  describedBy,
  invalid,
  disabled,
}: {
  value: V;
  onValueChange: (v: V) => void;
  items: { value: V; label: string }[];
  label: string;
  className?: string;
  /** Lets a visible caption point at the trigger with htmlFor. */
  id?: string;
  describedBy?: string;
  invalid?: boolean;
  /** A disabled fieldset reaches the trigger but not Base UI's own handling: pass this too for a read-only form. */
  disabled?: boolean;
}) {
  return (
    <BaseSelect.Root
      items={items}
      value={value}
      disabled={disabled}
      onValueChange={(v) => v != null && onValueChange(v as V)}
    >
      <BaseSelect.Trigger
        id={id}
        aria-label={label}
        aria-describedby={describedBy}
        aria-invalid={invalid || undefined}
        className={cn(
          "flex h-9 min-w-40 items-center justify-between gap-2 rounded-md border border-rule bg-paper px-3 text-sm text-ink hover:border-grey-300 disabled:cursor-default disabled:opacity-60 data-[popup-open]:border-grey-500",
          className,
        )}
      >
        <BaseSelect.Value />
        <BaseSelect.Icon>
          <ChevronsUpDown className="size-3.5 text-grey-500" aria-hidden />
        </BaseSelect.Icon>
      </BaseSelect.Trigger>
      <BaseSelect.Portal>
        <BaseSelect.Positioner sideOffset={6} alignItemWithTrigger={false} className="z-50">
          <BaseSelect.Popup className={cn(POPUP, "min-w-[var(--anchor-width)] p-1.5")}>
            <BaseSelect.List>
              {items.map((it) => (
                <BaseSelect.Item key={it.value} value={it.value} className={cn(ITEM, "relative pr-8")}>
                  <BaseSelect.ItemText>{it.label}</BaseSelect.ItemText>
                  <BaseSelect.ItemIndicator className="absolute right-2.5">
                    <Check className="size-3.5" aria-hidden />
                  </BaseSelect.ItemIndicator>
                </BaseSelect.Item>
              ))}
            </BaseSelect.List>
          </BaseSelect.Popup>
        </BaseSelect.Positioner>
      </BaseSelect.Portal>
    </BaseSelect.Root>
  );
}

/* ── Segmented control: one choice from a small set, shown all at once ── */

export function Segmented<V extends string>({
  value,
  onValueChange,
  options,
  label,
  disabled,
}: {
  value: V;
  onValueChange: (v: V) => void;
  options: { value: V; label: ReactNode; count?: number }[];
  label: string;
  disabled?: boolean;
}) {
  return (
    <ToggleGroup
      aria-label={label}
      disabled={disabled}
      value={[value]}
      onValueChange={(vals) => vals[0] && onValueChange(vals[0] as V)}
      className="flex shrink-0 rounded-md border border-rule bg-paper p-0.5"
    >
      {options.map((o) => (
        <Toggle
          key={o.value}
          value={o.value}
          className="flex h-8 items-center gap-1.5 rounded-[5px] px-3 text-sm whitespace-nowrap text-grey-700 hover:text-ink data-[pressed]:bg-grey-100 data-[pressed]:font-medium data-[pressed]:text-ink"
        >
          {o.label}
          {o.count !== undefined ? <span className="tnum text-xs font-normal text-muted">{o.count}</span> : null}
        </Toggle>
      ))}
    </ToggleGroup>
  );
}

/* ── Choice cards: a radio group where each option needs a sentence of explanation ── */

export function Choices<V extends string>({
  value,
  onValueChange,
  options,
  label,
  layout = "stack",
}: {
  value: V | null;
  onValueChange: (v: V) => void;
  options: { value: V; label: ReactNode; description?: ReactNode; tone?: "default" | "blocked" | "human" }[];
  label: string;
  layout?: "stack" | "row";
}) {
  return (
    <RadioGroup
      aria-label={label}
      value={value}
      onValueChange={(v) => onValueChange(v as V)}
      className={layout === "row" ? "flex flex-wrap gap-2" : "space-y-2"}
    >
      {options.map((o) => (
        <label
          key={o.value}
          className={cn(
            "flex cursor-pointer gap-3 rounded-[10px] border border-rule bg-paper transition-colors hover:border-grey-300 has-[[data-checked]]:border-ink has-[[data-checked]]:bg-grey-50",
            layout === "row" ? "items-center px-3 py-2 text-sm" : "items-start px-3.5 py-3",
          )}
        >
          <Radio.Root
            value={o.value}
            className={cn(
              "grid size-4 shrink-0 place-items-center rounded-full border border-grey-300 bg-paper data-[checked]:border-ink data-[checked]:bg-ink",
              layout === "stack" && "mt-0.5",
            )}
          >
            <Radio.Indicator className="size-1.5 rounded-full bg-paper" />
          </Radio.Root>
          <span className="min-w-0">
            <span
              className={cn(
                "block text-sm font-medium",
                o.tone === "blocked" && "text-blocked",
                o.tone === "human" && "text-human",
              )}
            >
              {o.label}
            </span>
            {o.description ? (
              <span className="mt-0.5 block text-[13px] leading-snug text-muted">{o.description}</span>
            ) : null}
          </span>
        </label>
      ))}
    </RadioGroup>
  );
}

/* ── Checkbox ── */

export function Checkbox({
  checked,
  onCheckedChange,
  children,
  describedBy,
  invalid,
  disabled,
  className,
}: {
  checked: boolean;
  onCheckedChange: (v: boolean) => void;
  children: ReactNode;
  className?: string;
  /** Ids of help or error text for this box. */
  describedBy?: string;
  invalid?: boolean;
  /** The box is a span, so a disabled fieldset does not reach it: pass this explicitly. */
  disabled?: boolean;
}) {
  return (
    <label className={cn("flex items-start gap-3 text-sm", disabled ? "cursor-default" : "cursor-pointer", className)}>
      <BaseCheckbox.Root
        checked={checked}
        onCheckedChange={(v) => onCheckedChange(Boolean(v))}
        disabled={disabled}
        aria-describedby={describedBy}
        aria-invalid={invalid || undefined}
        className="mt-0.5 grid size-4 shrink-0 place-items-center rounded-[4px] border border-grey-300 bg-paper data-[checked]:border-ink data-[checked]:bg-ink data-[disabled]:opacity-60"
      >
        <BaseCheckbox.Indicator>
          <Check className="size-3 text-paper" strokeWidth={3} aria-hidden />
        </BaseCheckbox.Indicator>
      </BaseCheckbox.Root>
      <span className="leading-snug">{children}</span>
    </label>
  );
}

/* ── Dialogs ── */

const BACKDROP =
  "fixed inset-0 z-50 bg-ink/25 transition-opacity duration-150 data-[ending-style]:opacity-0 data-[starting-style]:opacity-0";
const MODAL = cn(
  POPUP,
  "fixed top-1/2 left-1/2 z-50 w-[min(480px,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 p-5",
);

/**
 * Asks before an action that is hard to undo. The confirm button repeats the action's name. Opened by its
 * `trigger`, or controlled with `open` and `onOpenChange` when another control (a checkbox) asks.
 */
export function Confirm({
  trigger,
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  onConfirm,
  danger,
}: {
  trigger?: ReactElement;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  title: string;
  description: ReactNode;
  confirmLabel: string;
  onConfirm: () => void;
  danger?: boolean;
}) {
  const t = useTranslations("common");
  return (
    <AlertDialog.Root open={open} onOpenChange={onOpenChange ? (o) => onOpenChange(o) : undefined}>
      {trigger ? <AlertDialog.Trigger render={trigger} /> : null}
      <AlertDialog.Portal>
        <AlertDialog.Backdrop className={BACKDROP} />
        <AlertDialog.Popup className={MODAL}>
          <AlertDialog.Title className="text-base font-semibold">{title}</AlertDialog.Title>
          <AlertDialog.Description className="mt-1.5 text-sm leading-relaxed text-grey-700">
            {description}
          </AlertDialog.Description>
          <div className="mt-5 flex justify-end gap-2">
            <AlertDialog.Close render={<Button variant="ghost" />}>{t("cancel")}</AlertDialog.Close>
            <AlertDialog.Close render={<Button variant={danger ? "danger" : "primary"} onClick={onConfirm} />}>
              {confirmLabel}
            </AlertDialog.Close>
          </div>
        </AlertDialog.Popup>
      </AlertDialog.Portal>
    </AlertDialog.Root>
  );
}

export function Modal({
  open,
  onOpenChange,
  trigger,
  title,
  description,
  children,
  className,
}: {
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  trigger?: ReactElement;
  title: string;
  description?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  const t = useTranslations("common");
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange ? (o) => onOpenChange(o) : undefined}>
      {trigger ? <Dialog.Trigger render={trigger} /> : null}
      <Dialog.Portal>
        <Dialog.Backdrop className={BACKDROP} />
        <Dialog.Popup className={cn(MODAL, className)}>
          <Dialog.Title className="pr-8 text-base font-semibold">{title}</Dialog.Title>
          {description ? (
            <Dialog.Description className="mt-1.5 text-sm leading-relaxed text-grey-700">
              {description}
            </Dialog.Description>
          ) : null}
          {children}
          {/* After the content so initial focus lands on the first field, not on Close. */}
          <Dialog.Close
            aria-label={t("close")}
            className="absolute top-4 right-4 grid size-7 place-items-center rounded-md text-grey-500 hover:bg-grey-100 hover:text-ink"
          >
            <X className="size-4" aria-hidden />
          </Dialog.Close>
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export const ModalClose = Dialog.Close;

/**
 * Moves focus once React has committed and a closing dialog has tried to return focus.
 * Use when the control that opened a Confirm disappears with the action, so focus would
 * otherwise fall to the page body. When the trigger unmounts with its row, Base UI's own focus
 * return targets a detached node and does nothing, so this frame-later focus is what lands.
 */
export function focusAfterClose(find: () => HTMLElement | null | undefined) {
  requestAnimationFrame(() => find()?.focus());
}

/** The item at the same position after one was removed, or the new last one. */
export function sameOrLast<T>(items: ArrayLike<T>, index: number): T | undefined {
  return items.length ? items[Math.min(index, items.length - 1)] : undefined;
}
