"use client";

import { Menu } from "@base-ui/react/menu";
import { Check } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useTransition } from "react";
import { LOCALES, LOCALE_COOKIE, LOCALE_LABELS, resolveLocale, type Locale } from "@/i18n/locales";
import { cn } from "@/lib/cn";

const ONE_YEAR_S = 31536000;

/** Shared by both variants: remember the choice in a cookie the server reads, then re-render on the server. */
function useSwitchLocale() {
  const router = useRouter();
  const [pending, start] = useTransition();
  const choose = (next: Locale) => {
    const secure = window.location.protocol === "https:" ? "; secure" : "";
    document.cookie = `${LOCALE_COOKIE}=${next}; path=/; max-age=${ONE_YEAR_S}; samesite=lax${secure}`;
    start(() => router.refresh());
  };
  return { choose, pending };
}

/** Plain buttons, for the landing footer. */
export function LanguageSwitch({ className }: { className?: string }) {
  const t = useTranslations("common");
  const locale = useLocale();
  const { choose, pending } = useSwitchLocale();
  return (
    <div role="group" aria-label={t("language")} className={className}>
      {LOCALES.map((value) => (
        <button
          key={value}
          type="button"
          lang={value}
          aria-pressed={locale === value}
          disabled={pending}
          onClick={() => choose(value)}
          className="rounded px-1.5 py-0.5 text-xs text-muted aria-pressed:font-medium aria-pressed:text-ink"
        >
          {LOCALE_LABELS[value]}
        </button>
      ))}
    </div>
  );
}

/** Radio items for inside a Base UI menu, so arrow keys and Enter work and the markup stays valid. */
export function LanguageMenuItems() {
  const t = useTranslations("common");
  const locale = resolveLocale(useLocale());
  const { choose, pending } = useSwitchLocale();
  return (
    <Menu.Group>
      <Menu.GroupLabel className="px-2.5 pt-1 pb-1 text-xs text-muted">{t("language")}</Menu.GroupLabel>
      <Menu.RadioGroup value={locale} onValueChange={(v) => choose(resolveLocale(String(v)))}>
        {LOCALES.map((value) => (
          <Menu.RadioItem
            key={value}
            value={value}
            lang={value}
            disabled={pending}
            closeOnClick={false}
            className={cn(
              "flex w-full cursor-default items-center gap-2.5 rounded-md px-2.5 py-2 text-left text-sm text-ink outline-none select-none data-[disabled]:opacity-45 data-[highlighted]:bg-grey-100",
            )}
          >
            <span className="flex-1">{LOCALE_LABELS[value]}</span>
            <Menu.RadioItemIndicator>
              <Check className="size-3.5" aria-hidden />
            </Menu.RadioItemIndicator>
          </Menu.RadioItem>
        ))}
      </Menu.RadioGroup>
    </Menu.Group>
  );
}
