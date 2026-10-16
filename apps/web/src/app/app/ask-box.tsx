"use client";

import { Search } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { PackIcon } from "@/components/pack-icon";
import { Button, ButtonLink, SimTag } from "@/components/ui";
import { useToast } from "@/components/base";
import { useErrorText } from "@/lib/api/use-error-text";
import { useSuggestPack } from "@/lib/queries/catalog";

// The label is translated; the query sent to the suggestion API stays English because its keyword match is English-only.
const SUGGESTIONS = [
  { key: "reconcile", query: "Match last week's orders to Stripe payouts" },
  { key: "invoices", query: "Chase wholesale invoices that are past due" },
  { key: "refunds", query: "Handle refund requests from support email" },
  { key: "reorder", query: "Tell me what to reorder every Monday" },
  { key: "translate", query: "Translate our catalog for a Japanese store" },
] as const;

export function AskBox() {
  const t = useTranslations("overview.ask");
  const [q, setQ] = useState("");
  // Set when a chip fills the input: the English query to send while the input shows the translated label.
  const [chipQuery, setChipQuery] = useState<string | null>(null);
  const suggest = useSuggestPack();
  const toast = useToast();
  const errorText = useErrorText();
  const submit = (text = chipQuery ?? q) => {
    if (suggest.isPending || text.trim().length < 3) return;
    suggest.mutate({ body: { text: text.trim() } }, { onError: (e) => toast(t("failed"), errorText(e), "blocked") });
  };

  return (
    <section className="panel" data-tour="ask-box">
      <div className="flex items-center gap-3 px-4">
        <Search className="size-4 shrink-0 text-grey-500" strokeWidth={1.75} aria-hidden />
        <label htmlFor="ask" className="sr-only">
          {t("label")}
        </label>
        <input
          id="ask"
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setChipQuery(null);
            if (suggest.data) suggest.reset();
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.nativeEvent.isComposing) submit();
          }}
          placeholder={t("placeholder")}
          name="ask"
          className="h-12 w-full bg-transparent text-[15px] outline-none placeholder:text-grey-500"
        />
        {q.trim().length >= 3 ? (
          <Button variant="secondary" className="h-8 shrink-0" onClick={() => submit()} disabled={suggest.isPending}>
            {t("suggest")}
          </Button>
        ) : null}
        {q ? (
          <button
            type="button"
            onClick={() => {
              setQ("");
              setChipQuery(null);
              suggest.reset();
            }}
            className="shrink-0 text-xs text-muted hover:text-ink"
          >
            {t("clear")}
          </button>
        ) : null}
      </div>
      <div
        aria-live="polite"
        className={suggest.data || suggest.isPending ? "border-t border-rule px-4 py-3.5 text-sm" : undefined}
      >
        {suggest.isPending ? <p className="text-muted">{t("finding")}</p> : null}
        {suggest.data ? (
          suggest.data.pack ? (
            <>
              <div className="flex items-center gap-2">
                <PackIcon slug={suggest.data.pack.slug} className="size-6 [&_svg]:size-3" />
                <span className="font-medium">{suggest.data.pack.name}</span>
                {suggest.data.simulated ? <SimTag>{t("simulated")}</SimTag> : null}
              </div>
              <ol className="mt-2.5 list-decimal space-y-1 pl-5 text-grey-700">
                {suggest.data.steps.map((s) => (
                  <li key={s}>{s}</li>
                ))}
              </ol>
              {suggest.data.pack.installed ? (
                <ButtonLink href={`/app/runs/new?pack=${suggest.data.pack.slug}`} className="mt-3 h-8">
                  {t("startThis")}
                </ButtonLink>
              ) : (
                // A pack that isn't hired can't start a run yet: send the person to hire it first.
                <ButtonLink href={`/app/marketplace/${suggest.data.pack.slug}`} className="mt-3 h-8">
                  {t("hireThis")}
                </ButtonLink>
              )}
            </>
          ) : (
            <p className="flex flex-wrap items-center gap-2 text-grey-700">
              {suggest.data.steps[0]}
              {suggest.data.simulated ? <SimTag>{t("simulated")}</SimTag> : null}
            </p>
          )
        ) : null}
      </div>
      {!suggest.data ? (
        // The chips wrap from sm up. On a phone they scroll sideways, with a fade at the edge and room past
        // the last chip so the fade never covers it.
        <div className="relative border-t border-rule after:pointer-events-none after:absolute after:inset-y-0 after:right-0 after:w-10 after:rounded-br-[12px] after:bg-linear-to-l after:from-paper after:to-transparent sm:after:hidden">
          <div className="flex [scrollbar-width:none] gap-2 overflow-x-auto px-4 py-2.5 pr-10 sm:flex-wrap sm:pr-4">
            {SUGGESTIONS.map(({ key, query }) => (
              <button
                key={key}
                type="button"
                onClick={() => {
                  setQ(t(`suggestions.${key}`));
                  setChipQuery(query);
                  submit(query);
                }}
                className="inline-flex min-h-9 shrink-0 items-center rounded-full border border-rule bg-stage px-3 text-[13px] whitespace-nowrap text-grey-700 hover:border-grey-300 hover:text-ink"
              >
                {t(`suggestions.${key}`)}
              </button>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}
