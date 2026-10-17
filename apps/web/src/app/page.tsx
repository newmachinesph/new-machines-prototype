import { getTranslations } from "next-intl/server";
import { LanguageSwitch } from "@/components/language-switch";
import { SimTag } from "@/components/ui";
import { Lockup } from "@/design-system/logo/Lockup";
import { safeNext, signedInArea } from "@/lib/auth/next-path";
import { RunRecord } from "./run-record";
import { SignInForm } from "./sign-in-form";

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

export default async function LandingPage({ searchParams }: { searchParams: SearchParams }) {
  const t = await getTranslations("landing");
  // The guard sends a signed-out visitor here with the page they asked for; name it in the title.
  const { next } = await searchParams;
  const area = signedInArea(safeNext(Array.isArray(next) ? next[0] : next) ?? "");
  return (
    <div className="min-h-dvh bg-paper">
      <header className="mx-auto flex max-w-[1600px] items-center px-5 pt-6 sm:px-10 lg:px-16 lg:pt-8">
        <Lockup trim className="h-9 w-auto text-ink sm:h-10" />
      </header>

      <main id="main">
        <div className="mx-auto grid max-w-[1600px] grid-cols-1 gap-12 px-5 pt-12 pb-14 sm:px-10 lg:grid-cols-[minmax(0,1fr)_380px] lg:items-start lg:gap-20 lg:px-16 lg:pt-16 lg:pb-16 2xl:grid-cols-[minmax(0,1fr)_420px]">
          <div className="max-w-[54rem]">
            <h1 className="text-[clamp(2.5rem,5vw,5.25rem)] leading-[0.98] font-semibold tracking-[-0.045em] text-balance">
              {t("headline")}
            </h1>
            <p className="mt-7 max-w-[56ch] text-[clamp(1.0625rem,1.2vw,1.25rem)] leading-relaxed text-grey-700">
              {t("lede")}
            </p>
            <a
              href="#record"
              aria-labelledby="record-link"
              aria-describedby="record-summary"
              className="group mt-10 hidden max-w-[44rem] border-t-[3px] border-ink pt-5 lg:block"
            >
              <span id="record-summary" className="text-sm text-grey-700">
                {t("recordSummary")}
              </span>
              <span className="mt-3 flex flex-wrap items-center gap-x-7 gap-y-2 font-display text-[15px]" aria-hidden>
                {(["executed", "verified", "accepted", "settled"] as const).map((s) => (
                  <span key={s} className="flex items-center gap-2">
                    <svg viewBox="0 0 12 12" className="size-3" aria-hidden>
                      <path d="m2 6.5 2.5 2.5L10 3.5" fill="none" stroke="currentColor" strokeWidth="2" />
                    </svg>
                    {t(`strip.${s}`)}
                    {s === "settled" ? <SimTag className="font-sans" /> : null}
                  </span>
                ))}
              </span>
              <span id="record-link" className="link mt-3 inline-block text-sm group-hover:decoration-current">
                {t("recordLink")}
              </span>
            </a>
          </div>

          <div className="rounded-[14px] border border-rule bg-paper p-6 shadow-[0_1px_2px_rgb(17_17_17/0.04)] sm:p-7">
            <h2 className="text-lg font-semibold tracking-tight">
              {area ? t("signInTitleNext", { page: t(`continueTo.${area}`) }) : t("signInTitle")}
            </h2>
            <p className="mt-1 text-sm leading-relaxed text-muted">{t("signInHelp")}</p>
            <SignInForm />
          </div>
        </div>

        <RunRecord />
      </main>

      <footer className="mx-auto flex max-w-[1600px] flex-col gap-3 px-5 py-8 text-[13px] text-muted sm:flex-row sm:items-center sm:justify-between sm:px-10 lg:px-16">
        <p>{t("footerNote")}</p>
        <LanguageSwitch className="-ml-2.5 flex items-center gap-1 sm:-mr-2.5 sm:ml-0" />
      </footer>
    </div>
  );
}
