"use client";

import { useTranslations } from "next-intl";
import { useRef, useState } from "react";
import { Checkbox, Choices, Modal, ModalClose, focusAfterClose, useToast } from "@/components/base";
import { Button, ButtonLink, Callout, Id, KeyValues, MockTag, Section } from "@/components/ui";
import { useErrorText } from "@/lib/api/use-error-text";
import { usd } from "@/lib/format";
import { ORG_ID, useAgentById, useInstallPack } from "@/lib/queries/catalog";
import { useFormat } from "@/lib/use-format";
import type { Pack } from "@/lib/types";

const CAPS = [500, 2000, 5000];

export function InstallReview({ pack: p }: { pack: Pack }) {
  const t = useTranslations("marketplace.install");
  const tc = useTranslations("common");
  const { money, list } = useFormat();
  const errorText = useErrorText();
  const [cap, setCap] = useState(2000);
  const [pool, setPool] = useState(true);
  const [agree, setAgree] = useState(false);
  const [hired, setHired] = useState<string | null>(null);
  const agentById = useAgentById();
  const install = useInstallPack();
  const confirmation = useRef<HTMLDivElement>(null);
  const toast = useToast();

  const needsReviewers = p.estimate.humanMax.amountMinor > 0;
  const hire = () =>
    install.mutate(
      { path: { org_id: ORG_ID }, body: { packSlug: p.slug, capMinor: cap, reviewerPool: pool } },
      {
        onSuccess: (res) => {
          setHired(res.summary);
          toast(t("hiredToast", { name: p.name }), res.summary);
          // The hire button goes away with the form, so move focus to the confirmation.
          focusAfterClose(() => confirmation.current);
        },
        onError: (e) => toast(t("hireFailed"), errorText(e), "blocked"),
      },
    );

  if (hired !== null) {
    return (
      <div ref={confirmation} tabIndex={-1} className="outline-none">
        <Callout
          tone="info"
          announce={false}
          title={t("hiredTitle", { name: p.name, version: p.version })}
          action={
            <ButtonLink href="/app" variant="secondary">
              {t("goHome")}
            </ButtonLink>
          }
        >
          {hired} {t("hiredBody", { version: p.version })}
        </Callout>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
      <div className="space-y-6">
        <Section title={t("access")}>
          <ul className="divide-y divide-rule">
            {p.connectors.map((k) => (
              <li
                key={k.app}
                className="flex flex-col gap-1 px-5 py-3.5 sm:flex-row sm:items-center sm:justify-between"
              >
                <div className="flex items-center gap-2 text-sm font-medium">
                  {k.app}
                  {k.mocked ? <MockTag /> : null}
                </div>
                <div className="text-sm text-grey-700">
                  {k.access === "read" ? tc("readOnly") : t("writeWithApproval")}
                </div>
              </li>
            ))}
            <li className="px-5 py-3.5 text-sm text-muted">
              {t("capabilities")}
              <span className="mt-1.5 flex flex-wrap gap-1.5">
                {[...new Set(p.agents.flatMap((a) => agentById(a)?.capabilities ?? []))].map((c) => (
                  <Id key={c} className="rounded bg-grey-100 px-1.5 py-0.5 text-[11px]">
                    {c}
                  </Id>
                ))}
              </span>
              <div className="mt-1">{t("capabilitiesNote")}</div>
            </li>
          </ul>
        </Section>

        <Section title={t("capTitle")}>
          <div className="px-5 py-4">
            <Choices
              label={t("capTitle")}
              layout="row"
              value={String(cap)}
              onValueChange={(v) => setCap(Number(v))}
              options={CAPS.map((c) => ({ value: String(c), label: <span className="tnum">{money(usd(c))}</span> }))}
            />
            <p className="mt-3 text-sm text-muted">{t("capNote")}</p>
          </div>
        </Section>

        {needsReviewers ? (
          <Section title={t("reviewers")}>
            <div className="px-5 py-4">
              <Checkbox checked={pool} onCheckedChange={setPool}>
                {t("poolLabel")}
                <span className="mt-1 block text-muted">{t("poolNote")}</span>
              </Checkbox>
            </div>
          </Section>
        ) : null}
      </div>

      <div className="space-y-6">
        <Section title={t("summary")}>
          <div className="px-5 py-2">
            <KeyValues
              rows={[
                { label: t("pack"), value: `${p.name} ${p.version}` },
                { label: t("version"), value: t("pinned") },
                {
                  label: t("perRunLabel"),
                  value: (
                    <span className="tnum">
                      {t("perRunValue", { min: money(p.estimate.aiMin), max: money(p.estimate.aiMax) })}
                    </span>
                  ),
                },
                { label: t("cap"), value: <span className="tnum">{t("capPerRun", { amount: money(usd(cap)) })}</span> },
                { label: t("region"), value: list(p.regions) },
              ]}
            />
          </div>
          <div className="border-t border-rule px-5 py-4">
            <Checkbox checked={agree} onCheckedChange={setAgree}>
              {t("agree")}
            </Checkbox>
            <Modal
              trigger={
                <button type="button" className="link mt-1.5 ml-7 text-sm">
                  {t("readContract")}
                </button>
              }
              title={t("contractTitle", { name: p.name, version: p.version })}
              description={t("contractDescription")}
            >
              <ul className="mt-4 list-disc space-y-2 pl-5 text-sm leading-relaxed text-grey-700">
                <li>{t("contract.pay")}</li>
                <li>{t("contract.delivered")}</li>
                <li>{t("contract.reviewers")}</li>
                <li>{t("contract.data", { regions: list(p.regions) })}</li>
                <li>{t("contract.updates")}</li>
              </ul>
              <div className="mt-5 flex justify-end">
                <ModalClose render={<Button variant="secondary" />}>{tc("close")}</ModalClose>
              </div>
            </Modal>
            <Button className="mt-4 w-full" disabled={!agree || install.isPending} onClick={hire}>
              {t("hire", { name: p.name })}
            </Button>
          </div>
        </Section>
      </div>
    </div>
  );
}
