"use client";

import { Braces } from "lucide-react";
import { useTranslations } from "next-intl";
import { MenuGroup, MenuGroupLabel, MenuItem, MenuPopup, MenuRoot, MenuTrigger } from "@/components/base";
import { Id } from "@/components/ui";
import { isCel, type CelGroup, type CelOption } from "@/lib/builder/cel-fields";
import { useReadOnly } from "./read-only";

const GROUPS: readonly CelGroup[] = ["input", "memory", "steps", "item"];
export const FIELD_CLASS =
  "mt-1.5 w-full rounded-md border border-grey-300 px-3 text-sm outline-none focus:border-ink aria-[invalid=true]:border-blocked";

/**
 * A setting that may be plain text or a CEL expression. The picker lists what the step can read and writes the
 * chosen field as `=<expression>`. `bare` is for a value that is always CEL (a decision rule's condition): the
 * field is inserted without the "=". `onChange(value, record)`: typing passes `false` (the settings panel records
 * one undo step per field visit); choosing from the picker passes `true`.
 */
export function CelField({
  id,
  label,
  value,
  onChange,
  options,
  multiline,
  bare,
  help,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string, record: boolean) => void;
  options: CelOption[];
  multiline?: boolean;
  bare?: boolean;
  help?: string;
}) {
  const t = useTranslations("studioCel");
  const readOnly = useReadOnly();
  const groups = GROUPS.map((g) => [g, options.filter((o) => o.group === g)] as const).filter(
    ([, list]) => list.length,
  );
  const hint = `${id}-hint`;
  const mono = bare || isCel(value) ? "font-mono text-[13px]" : "";
  /** Data labels as sent; our own fixed words translated, keeping the step id in front of "results". */
  const labelOf = (o: CelOption) => {
    if (!o.fixed) return o.label;
    const word = t(`option.${o.fixed}`);
    return o.fixed === "results" ? `${o.expr.split(".")[1]} · ${word}` : word;
  };
  return (
    <div>
      <div className="flex items-center justify-between gap-2">
        <label htmlFor={id} className="text-sm font-medium">
          {label}
        </label>
        {groups.length ? (
          <MenuRoot>
            <MenuTrigger
              aria-label={t("insert", { field: label })}
              disabled={readOnly}
              className="inline-flex h-7 items-center gap-1 rounded-md px-1.5 text-xs text-muted hover:bg-grey-100 hover:text-ink disabled:cursor-default disabled:opacity-60 disabled:hover:bg-transparent disabled:hover:text-muted"
            >
              <Braces className="size-3.5" aria-hidden />
              {t("fields")}
            </MenuTrigger>
            <MenuPopup className="max-h-80 overflow-y-auto">
              {groups.map(([group, list]) => (
                <MenuGroup key={group}>
                  <MenuGroupLabel>{t(`group.${group}`)}</MenuGroupLabel>
                  {list.map((o) => (
                    <MenuItem key={o.expr} onClick={() => onChange(bare ? o.expr : `=${o.expr}`, true)}>
                      <span className="min-w-0 flex-1 truncate">{labelOf(o)}</span>
                      <Id className="text-[11px]">{o.expr}</Id>
                    </MenuItem>
                  ))}
                </MenuGroup>
              ))}
            </MenuPopup>
          </MenuRoot>
        ) : null}
      </div>
      {multiline ? (
        <textarea
          id={id}
          rows={4}
          aria-describedby={hint}
          className={`${FIELD_CLASS} py-2 leading-relaxed ${mono}`}
          value={value}
          onChange={(e) => onChange(e.target.value, false)}
        />
      ) : (
        <input
          id={id}
          aria-describedby={hint}
          className={`${FIELD_CLASS} h-10 ${mono}`}
          value={value}
          onChange={(e) => onChange(e.target.value, false)}
        />
      )}
      <p id={hint} className="mt-1 text-xs text-muted">
        {help ? `${help} ` : ""}
        {bare ? t("isCondition") : isCel(value) ? t("isCel") : t("isText")}
      </p>
    </div>
  );
}
