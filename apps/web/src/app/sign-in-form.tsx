"use client";

import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Button, MockTag } from "@/components/ui";
import { signInMessage, type SignInError } from "@/lib/auth/messages";
import { DEFAULT_AFTER_SIGN_IN, safeNext } from "@/lib/auth/next-path";
import { useSession } from "@/lib/auth/session";
import { env } from "@/lib/env";

export function SignInForm() {
  const t = useTranslations("landing.signIn");
  const tError = useTranslations("errors.signIn");
  const router = useRouter();
  const { signInWithGoogle, signInWithEmail, status } = useSession();
  const [busy, setBusy] = useState<"google" | "email" | null>(null);
  const [error, setError] = useState<SignInError | null>(null);

  useEffect(() => {
    if (status !== "signed-in") return;
    // Back to the deep link the guard sent the visitor away from, when it is a safe in-app path.
    const next = safeNext(new URLSearchParams(window.location.search).get("next"));
    router.push(next ?? DEFAULT_AFTER_SIGN_IN);
  }, [status, router]);

  const go = async (how: "google" | "email", email = "", password = "") => {
    setBusy(how);
    setError(null);
    try {
      await (how === "google" ? signInWithGoogle() : signInWithEmail(email, password));
    } catch (e) {
      setError(signInMessage(how, e));
      setBusy(null);
    }
  };

  return (
    <div className="mt-5 space-y-4">
      {env.NEXT_PUBLIC_AUTH_MOCK ? (
        <p className="text-xs text-muted">
          <MockTag /> {t("mockNote")}
        </p>
      ) : null}
      <Button variant="secondary" className="h-11 w-full" onClick={() => void go("google")} disabled={busy !== null}>
        <svg viewBox="0 0 18 18" className="size-4" aria-hidden>
          <path
            fill="#4285F4"
            d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.92c1.7-1.57 2.68-3.88 2.68-6.62Z"
          />
          <path
            fill="#34A853"
            d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.92-2.26c-.8.54-1.84.86-3.04.86-2.34 0-4.32-1.58-5.03-3.7H.96v2.33A9 9 0 0 0 9 18Z"
          />
          <path
            fill="#FBBC05"
            d="M3.97 10.72A5.4 5.4 0 0 1 3.68 9c0-.6.1-1.18.29-1.72V4.95H.96A9 9 0 0 0 0 9c0 1.45.35 2.83.96 4.05l3.01-2.33Z"
          />
          <path
            fill="#EA4335"
            d="M9 3.58c1.32 0 2.5.45 3.44 1.35l2.58-2.58A9 9 0 0 0 .96 4.95l3.01 2.33C4.68 5.16 6.66 3.58 9 3.58Z"
          />
        </svg>
        {busy === "google" ? t("signingIn") : t("google")}
      </Button>
      <div className="flex items-center gap-3 text-xs text-muted">
        <span className="h-px flex-1 bg-rule" />
        {t("orDemoLogin")}
        <span className="h-px flex-1 bg-rule" />
      </div>
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          const data = new FormData(e.currentTarget);
          void go("email", String(data.get("email") ?? ""), String(data.get("password") ?? ""));
        }}
      >
        <label className="block">
          <span className="text-sm font-medium">{t("email")}</span>
          <input
            name="email"
            type="email"
            autoComplete="username"
            placeholder={t("emailPlaceholder")}
            className="mt-1.5 h-10 w-full rounded-md border border-grey-300 bg-paper px-3 text-sm outline-none focus:border-ink"
          />
        </label>
        <label className="block">
          <span className="text-sm font-medium">{t("password")}</span>
          <input
            name="password"
            type="password"
            autoComplete="current-password"
            className="mt-1.5 h-10 w-full rounded-md border border-grey-300 bg-paper px-3 text-sm outline-none focus:border-ink"
          />
        </label>
        {error ? (
          <p role="alert" className="text-sm text-blocked">
            {tError(error)}
          </p>
        ) : null}
        <Button type="submit" className="h-11 w-full" disabled={busy !== null}>
          {busy === "email" ? t("signingIn") : t("submit")}
        </Button>
      </form>
      <p className="text-[13px] leading-relaxed text-muted">{t("joinNote")}</p>
    </div>
  );
}
