"use client";

import { useReactFlow } from "@xyflow/react";
import { useTranslations } from "next-intl";
import { useId, useMemo, useState } from "react";
import { ActorGlyph, Pill } from "@/components/ui";
import { useFeeLabel } from "@/lib/listing-fee";
import type { NewStep } from "@/lib/builder/graph";
import { paletteEntries, type PaletteEntry } from "@/lib/builder/palette";
import { STEP_ACTOR } from "@/lib/builder/routes";
import { useEditor, useEditorApi } from "@/lib/builder/store";
import { STEP_MIME } from "./editor-canvas";

// Agents from other workspaces come after the platform's and the team's, in their own section.
const SECTIONS = [
  { group: "step", listed: false },
  { group: "agent", listed: false },
  { group: "agent", listed: true },
  { group: "tool", listed: false },
  { group: "space", listed: false },
] as const;

/**
 * Everything a pack can use. Drag an entry onto the canvas, or choose it to add it beside the selected step.
 * `disabled` turns both off, for a pack the signed-in member may only read.
 */
export function PalettePanel({ disabled = false }: { disabled?: boolean }) {
  const t = useTranslations("studioPalette");
  const tc = useTranslations("studioCanvas");
  const tl = useTranslations("paletteListed");
  const feeLabel = useFeeLabel();
  const api = useEditorApi();
  const palette = useEditor((s) => s.palette);
  const { fitView } = useReactFlow();
  const [query, setQuery] = useState("");
  const baseId = useId();
  const entries = useMemo(() => paletteEntries(palette), [palette]);
  const labelOf = (e: PaletteEntry) => (e.kind === "step" ? t(`add.${e.add}`) : e.title);
  const summaryOf = (e: PaletteEntry) => (e.kind === "agent" || e.kind === "tool" ? e.summary : "");
  const q = query.trim().toLowerCase();
  const shown = entries.filter((e) => !q || `${labelOf(e)} ${summaryOf(e)}`.toLowerCase().includes(q));

  const add = (step: NewStep) => {
    const id = api.getState().addStep(step);
    requestAnimationFrame(() => void fitView({ nodes: [{ id }], maxZoom: 1, duration: 200 }));
  };

  return (
    <div className="space-y-4 p-3">
      <label className="block text-sm font-medium">
        {t("search")}
        <input
          type="search"
          className="mt-1.5 h-9 w-full rounded-md border border-grey-300 px-3 text-sm outline-none focus:border-ink"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </label>
      <p className="text-xs text-muted">{t("help")}</p>
      {SECTIONS.map(({ group, listed }) => {
        const list = shown.filter(
          (e) => e.kind === group && (group !== "agent" || (e.kind === "agent" && !!e.listing) === listed),
        );
        if (!list.length) return null;
        return (
          <section key={`${group}-${listed}`}>
            <h3 className="label mb-1.5">{listed ? tl("heading") : t(`group.${group}`)}</h3>
            <ul className="space-y-1.5">
              {list.map((e) => {
                const listing = e.kind === "agent" ? e.listing : undefined;
                const fee = `${baseId}-${e.key}-fee`;
                const blocked = e.kind === "tool" && e.blocked;
                const off = disabled || blocked;
                const why = `${baseId}-${e.key}-why`;
                return (
                  <li key={e.key}>
                    <button
                      type="button"
                      disabled={off}
                      draggable={!off}
                      aria-describedby={blocked ? why : listing ? fee : undefined}
                      title={listing ? tl("feeNote") : undefined}
                      onDragStart={(ev) => {
                        if (off) return;
                        ev.dataTransfer.setData(STEP_MIME, JSON.stringify(e.step));
                        ev.dataTransfer.effectAllowed = "copy";
                      }}
                      onClick={() => add(e.step)}
                      className="flex w-full cursor-grab items-start gap-2 rounded-md border border-rule bg-paper px-2.5 py-2 text-left text-sm hover:border-grey-300 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      <ActorGlyph actor={STEP_ACTOR[e.step.type]} className="mt-1 size-2.5" />
                      <span className="min-w-0 flex-1">
                        <span className="block font-medium">{labelOf(e)}</span>
                        {summaryOf(e) ? (
                          <span className="block truncate text-xs text-muted">{summaryOf(e)}</span>
                        ) : null}
                        {listing ? (
                          <span className="block truncate text-xs text-muted">
                            {tl("by", { publisher: listing.publisher, fee: feeLabel(listing) })}
                          </span>
                        ) : null}
                        {e.kind === "tool" && e.writes ? (
                          <Pill tone="human" className="mt-1">
                            {tc("changesData")}
                          </Pill>
                        ) : null}
                        {e.kind === "agent" && e.team ? (
                          <Pill tone="machine" className="mt-1">
                            {t("team")}
                          </Pill>
                        ) : null}
                      </span>
                    </button>
                    {/* Outside the disabled button, so a reader can reach it; the button names it as its description. */}
                    {listing ? (
                      <p id={fee} className="sr-only">
                        {tl("feeNote")}
                      </p>
                    ) : null}
                    {blocked ? (
                      <p id={why} className="mt-1 px-2.5 text-xs text-blocked">
                        {t("blocked")}
                      </p>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          </section>
        );
      })}
      {shown.length === 0 ? <p className="text-sm text-muted">{t("noMatch")}</p> : null}
    </div>
  );
}
