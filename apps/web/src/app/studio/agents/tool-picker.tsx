"use client";

import { ChevronDown, ChevronRight, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useState, type ReactNode } from "react";
import { Checkbox } from "@/components/base";
import { Section } from "@/components/ui";
import type { PaletteTool } from "@/lib/api/gen/types.gen";

/** The messages a save put on one tool, and the id of the element that carries them. */
export type ToolErrors = { messages: string[]; id: string };

const INPUT =
  "h-10 w-full rounded-md border border-grey-300 px-3 text-sm outline-none focus:border-ink disabled:bg-grey-50 disabled:text-grey-700";

/** Tools by app, each app's in the palette's order; apps by name. */
function groupByApp(tools: PaletteTool[]): { app: string; tools: PaletteTool[] }[] {
  const byApp = new Map<string, PaletteTool[]>();
  for (const tool of tools) byApp.set(tool.app, [...(byApp.get(tool.app) ?? []), tool]);
  return [...byApp].map(([app, list]) => ({ app, tools: list })).sort((a, b) => a.app.localeCompare(b.app));
}

const matches = (tool: PaletteTool, query: string) =>
  `${tool.app} ${tool.name} ${tool.description}`.toLowerCase().includes(query);

/**
 * The tools an agent reads with: what is chosen, summarised at the top where it can be removed; then a search
 * box and the registry's tools by app, each app folded until it is opened, a search matches it, or a save put
 * an error on one of its tools. `stale` refs are chosen tools the registry no longer offers: each keeps a box,
 * so it can be removed. The picker sits outside the form's disabled fieldset, so a member who may only read
 * can still open an app and search; `disabled` reaches the boxes and the remove buttons instead.
 */
export function ToolPicker({
  tools,
  chosen,
  stale,
  max,
  disabled,
  errorsAt,
  children,
  onToggle,
}: {
  tools: PaletteTool[];
  chosen: string[];
  stale: string[];
  max: number;
  disabled: boolean;
  errorsAt: (ref: string) => ToolErrors;
  /** The help under the heading: what agents may do, and any error on the tools as a whole. */
  children?: ReactNode;
  onToggle: (ref: string, on: boolean) => void;
}) {
  const t = useTranslations("studioAgents");
  const searchId = useId();
  const [query, setQuery] = useState("");
  const [opened, setOpened] = useState<ReadonlySet<string>>(new Set());
  const needle = query.trim().toLowerCase();
  const atCap = chosen.length >= max;
  const byRef = new Map(tools.map((tool) => [tool.ref, tool]));
  const groups = groupByApp(needle ? tools.filter((tool) => matches(tool, needle)) : tools);
  const isOpen = (app: string, list: PaletteTool[]) =>
    needle !== "" || opened.has(app) || list.some((tool) => errorsAt(tool.ref).messages.length > 0);
  const toggleOpen = (app: string) =>
    setOpened((was) => {
      const next = new Set(was);
      if (next.has(app)) next.delete(app);
      else next.add(app);
      return next;
    });
  const nameOf = (ref: string) => {
    const tool = byRef.get(ref);
    return tool ? `${tool.app}: ${tool.name}` : ref;
  };

  return (
    <Section
      title={t("tools")}
      aside={<span className="text-xs text-muted">{t("toolsChosen", { n: chosen.length, max })}</span>}
    >
      <div className="space-y-4 p-5">
        {children}
        {chosen.length ? (
          <ul className="flex flex-wrap gap-1.5" aria-label={t("chosenTools")}>
            {chosen.map((ref) => (
              <li
                key={ref}
                className="flex items-center gap-1 rounded-full border border-rule bg-paper py-1 pr-1.5 pl-2.5 text-xs"
              >
                <span className={byRef.has(ref) ? undefined : "font-mono"}>{nameOf(ref)}</span>
                <button
                  type="button"
                  className="grid size-5 place-items-center rounded-full text-muted hover:bg-grey-100 hover:text-ink disabled:opacity-50"
                  disabled={disabled}
                  aria-label={t("removeTool", { name: nameOf(ref) })}
                  onClick={() => onToggle(ref, false)}
                >
                  <X className="size-3" aria-hidden />
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted">{t("noToolsChosen")}</p>
        )}
        {stale.map((ref) => {
          const err = errorsAt(ref);
          return (
            <div key={ref}>
              <Checkbox
                checked
                disabled={disabled}
                invalid={err.messages.length > 0}
                describedBy={err.messages.length ? err.id : undefined}
                onCheckedChange={(on) => onToggle(ref, on)}
              >
                <span className="font-mono text-[13px] font-medium">{ref}</span>
                <span className="block text-xs text-muted">{t("toolGone")}</span>
              </Checkbox>
              <ToolError {...err} />
            </div>
          );
        })}
        <div>
          <label htmlFor={searchId} className="sr-only">
            {t("toolSearch")}
          </label>
          <input
            id={searchId}
            type="search"
            className={INPUT}
            placeholder={t("toolSearchPlaceholder")}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              // Enter in the search box filters; it must not submit (and save) the agent form around it.
              if (e.key === "Enter") e.preventDefault();
            }}
          />
        </div>
        {groups.length === 0 ? (
          <p className="text-sm text-muted">{t("noToolMatches", { query: query.trim() })}</p>
        ) : (
          <ul className="space-y-2">
            {groups.map(({ app, tools: list }) => {
              const open = isOpen(app, list);
              const picked = list.filter((tool) => chosen.includes(tool.ref)).length;
              const Chevron = open ? ChevronDown : ChevronRight;
              return (
                <li key={app} className="rounded-md border border-rule">
                  <button
                    type="button"
                    className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-grey-50"
                    aria-expanded={open}
                    aria-controls={`${searchId}-app-${app}`}
                    onClick={() => toggleOpen(app)}
                  >
                    <Chevron className="size-4 shrink-0 text-muted" aria-hidden />
                    <span className="font-medium">{app}</span>
                    {/* A space in the button's name between the app and its count; flex lays no space out. */}{" "}
                    <span className="ml-auto text-xs text-muted">
                      {t("toolGroup", { n: list.length })}
                      {picked ? ` · ${t("toolGroupChosen", { n: picked })}` : null}
                    </span>
                  </button>
                  {open ? (
                    <div id={`${searchId}-app-${app}`} className="space-y-3 border-t border-rule p-3">
                      {list.map((tool) => {
                        const checked = chosen.includes(tool.ref);
                        const err = errorsAt(tool.ref);
                        return (
                          <div key={tool.ref}>
                            <Checkbox
                              checked={checked}
                              disabled={disabled || (atCap && !checked)}
                              invalid={err.messages.length > 0}
                              describedBy={err.messages.length ? err.id : undefined}
                              onCheckedChange={(on) => onToggle(tool.ref, on)}
                            >
                              <span className="font-medium">
                                {tool.app}: {tool.name}
                              </span>
                              <span className="block text-xs text-muted">{tool.description}</span>
                            </Checkbox>
                            <ToolError {...err} />
                          </div>
                        );
                      })}
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </Section>
  );
}

function ToolError({ id, messages }: ToolErrors) {
  if (!messages.length) return null;
  return (
    <p id={id} className="mt-1 text-xs text-blocked">
      {messages.join(" ")}
    </p>
  );
}
