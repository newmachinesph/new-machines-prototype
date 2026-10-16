"use client";

import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";
import { Button, MockTag } from "@/components/ui";
import { ApiError } from "@/lib/api/errors";
import { signInMessage, type SignInError } from "@/lib/auth/messages";
import { DEFAULT_AFTER_SIGN_IN, REVIEWER_AFTER_SIGN_IN, safeNext } from "@/lib/auth/next-path";
import { useSession } from "@/lib/auth/session";
import { env } from "@/lib/env";
import { useMe } from "@/lib/queries/me";

const FIELD =
  "h-10 w-full rounded-md border border-grey-300 bg-paper px-3 text-sm outline-none placeholder:text-grey-500 focus:border-ink";

export function SignInForm() {
  const t = useTranslations("landing.signIn");
  const tError = useTranslations("errors.signIn");
  const router = useRouter();
  const { signInWithGoogle, signInWithEmail, status } = useSession();
  // The shell asks for /v1/me next anyway; asking here only moves that one read earlier.
  const me = useMe(status === "signed-in");
  const sent = useRef(false);
  const [busy, setBusy] = useState<"google" | "email" | null>(null);
  const [error, setError] = useState<SignInError | null>(null);
  // Which fields were submitted empty: each says so under itself until it is typed in.
  const [missing, setMissing] = useState<{ email: boolean; password: boolean }>({ email: false, password: false });
  const [showPassword, setShowPassword] = useState(false);
  const id = useId();

  // Once signed out again, a sign-in that was under way is over: the buttons come back.
  const [lastStatus, setLastStatus] = useState(status);
  if (status !== lastStatus) {
    setLastStatus(status);
    if (status !== "signed-in") setBusy(null);
  }

  // A 401 from /v1/me means the session is already being ended; it must not send anyone into the app.
  const unauthorized = me.error instanceof ApiError && me.error.status === 401;
  // Signed in and on their way: the form is not live while /v1/me answers, unless that answer was a 401.
  const locked = !unauthorized && (busy !== null || status === "signed-in");
  // After a 401 nothing is under way any more, whatever was pressed.
  const pressed = unauthorized ? null : busy;

  useEffect(() => {
    if (status !== "signed-in") {
      // Signed out again (or not yet): another sign-in may redirect.
      sent.current = false;
      return;
    }
    if (sent.current || unauthorized) return;
    // Back to the deep link the guard sent the visitor away from, when it is a safe in-app path.
    const next = safeNext(new URLSearchParams(window.location.search).get("next"));
    if (!next && me.isPending) return;
    // Otherwise a reviewer lands in the reviewer portal and everyone else in the business workspace. When
    // /v1/me failed, the workspace shell reports it.
    const reviewer = me.data?.role === "reviewer";
    sent.current = true;
    router.push(next ?? (reviewer ? REVIEWER_AFTER_SIGN_IN : DEFAULT_AFTER_SIGN_IN));
  }, [status, router, unauthorized, me.isPending, me.data?.role]);

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
      <Button variant="secondary" className="h-11 w-full" onClick={() => void go("google")} disabled={locked}>
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
        {pressed === "google" ? t("signingIn") : t("google")}
      </Button>
      <div className="flex items-center gap-3 text-xs text-muted">
        <span className="h-px flex-1 bg-rule" />
        {t("orDemoLogin")}
        <span className="h-px flex-1 bg-rule" />
      </div>
      <form
        className="space-y-4"
        // The form says itself which field is empty, in the interface language, instead of the browser's tooltip.
        noValidate
        onSubmit={(e) => {
          e.preventDefault();
          const form = e.currentTarget;
          const data = new FormData(form);
          const email = String(data.get("email") ?? "").trim();
          const password = String(data.get("password") ?? "");
          const empty = { email: email === "", password: password === "" };
          setMissing(empty);
          if (empty.email || empty.password) {
            form.querySelector<HTMLInputElement>(empty.email ? 'input[name="email"]' : 'input[name="password"]')?.focus();
            return;
          }
          void go("email", email, password);
        }}
      >
        <div>
          <label htmlFor={`${id}-email`} className="text-sm font-medium">
            {t("email")}
          </label>
          <input
            id={`${id}-email`}
            name="email"
            type="email"
            autoComplete="username"
            inputMode="email"
            spellCheck={false}
            required
            aria-invalid={missing.email || undefined}
            aria-describedby={missing.email ? `${id}-email-error` : undefined}
            onChange={() => setMissing((m) => (m.email ? { ...m, email: false } : m))}
            placeholder={t("emailPlaceholder")}
            className={`mt-1.5 ${FIELD}`}
          />
          {missing.email ? (
            <p id={`${id}-email-error`} className="mt-1.5 text-xs text-blocked">
              {t("emailRequired")}
            </p>
          ) : null}
        </div>
        <div>
          <label htmlFor={`${id}-password`} className="text-sm font-medium">
            {t("password")}
          </label>
          <div className="relative mt-1.5">
            <input
              id={`${id}-password`}
              name="password"
              type={showPassword ? "text" : "password"}
              autoComplete="current-password"
              required
              aria-invalid={missing.password || undefined}
              aria-describedby={missing.password ? `${id}-password-error ${id}-password-hint` : `${id}-password-hint`}
              onChange={() => setMissing((m) => (m.password ? { ...m, password: false } : m))}
              className={`${FIELD} pr-16`}
            />
            <button
              type="button"
              aria-pressed={showPassword}
              onClick={() => setShowPassword((v) => !v)}
              className="absolute inset-y-0 right-0 rounded-r-md px-3 text-[13px] font-medium text-muted hover:text-ink"
            >
              {showPassword ? t("hide") : t("show")} <span className="sr-only">{t("passwordSuffix")}</span>
            </button>
          </div>
          {missing.password ? (
            <p id={`${id}-password-error`} className="mt-1.5 text-xs text-blocked">
              {t("passwordRequired")}
            </p>
          ) : null}
          <p id={`${id}-password-hint`} className="mt-1.5 text-xs text-muted">
            {t("passwordHint")}
          </p>
        </div>
        {error ? (
          <p role="alert" className="text-sm text-blocked">
            {tError(error)}
          </p>
        ) : null}
        <Button type="submit" className="h-11 w-full" disabled={locked}>
          {pressed === "email" ? t("signingIn") : t("submit")}
        </Button>
      </form>
      <div className="space-y-1 text-[13px] leading-relaxed text-muted">
        <p>{t("joinNoteMember")}</p>
        <p>{t("joinNoteReviewer")}</p>
      </div>
    </div>
  );
}
