"use client";

import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import { ActorGlyph, Button, Pill, Section } from "@/components/ui";
import type { Actor, Pack } from "@/lib/types";

type Line = { actor: Actor; key: string };

// Each line is a message key under `marketplace.trial.script` (reconciliation) or `.generic`.
const RECON_SCRIPT = [
  { actor: "machine", key: "recon.read" },
  { actor: "machine", key: "recon.retail" },
  { actor: "machine", key: "recon.finance" },
  { actor: "machine", key: "recon.decision" },
  { actor: "human", key: "recon.reviewer" },
  { actor: "machine", key: "recon.check" },
  { actor: "policy", key: "recon.blocked" },
] as const satisfies readonly Line[];

const GENERIC = [
  { actor: "machine", key: "generic.loaded" },
  { actor: "machine", key: "generic.done" },
  { actor: "machine", key: "generic.check" },
  { actor: "policy", key: "generic.inert" },
] as const satisfies readonly Line[];

export function SandboxTrial({ pack }: { pack: Pack }) {
  const t = useTranslations("marketplace.trial");
  const script = pack.slug === "order-payment-reconciliation" ? RECON_SCRIPT : GENERIC;
  const [step, setStep] = useState(-1);

  useEffect(() => {
    if (step < 0 || step >= script.length) return;
    const timer = setTimeout(() => setStep((s) => s + 1), 650);
    return () => clearTimeout(timer);
  }, [step, script.length]);

  const done = step >= script.length;

  return (
    <Section title={t("title")} aside={<Pill tone="quiet">{t("badge")}</Pill>}>
      <div className="px-5 py-4">
        <p className="text-sm text-grey-700">{t("intro")}</p>
        {step >= 0 ? (
          <ol className="mt-4 space-y-2" aria-live="polite">
            {script.slice(0, Math.max(0, step)).map((l, i) => (
              <li key={i} className="flex items-start gap-2.5 text-sm">
                <ActorGlyph actor={l.actor} className="mt-1 size-2.5" />
                <span>{t(`script.${l.key}`)}</span>
              </li>
            ))}
            {!done ? <li className="live-dot pl-5 text-sm text-muted">{t("running")}</li> : null}
          </ol>
        ) : null}
        <div className="mt-4 flex items-center gap-3">
          <Button variant={done ? "secondary" : "primary"} onClick={() => setStep(0)} disabled={step >= 0 && !done}>
            {done ? t("again") : step >= 0 ? t("running") : t("start")}
          </Button>
          {done ? <span className="text-sm text-muted">{t("finished")}</span> : null}
        </div>
      </div>
    </Section>
  );
}
