"use client";

import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { type ComponentProps, type ReactNode, useEffect, useId, useRef, useState } from "react";
import { Button, MockTag } from "@/components/ui";
import { ApiError } from "@/lib/api/errors";
import { type AuthErrorKey, createAccountMessage, signInMessage } from "@/lib/auth/messages";
import { DEFAULT_AFTER_SIGN_IN, REVIEWER_AFTER_SIGN_IN, safeNext } from "@/lib/auth/next-path";
import { useSession } from "@/lib/auth/session";
import { cn } from "@/lib/cn";
import { env } from "@/lib/env";
import { useMe } from "@/lib/queries/me";

const FIELD =
  "h-10 w-full rounded-md border border-grey-300 bg-paper px-3 text-sm outline-none placeholder:text-grey-500 focus:border-ink";

/** The shortest password a new account may have. The sign-in service's own floor is lower. */
export const MIN_PASSWORD_LENGTH = 8;
// Catches a name typed into the email box; the sign-in service does the real check.
const EMAIL_SHAPE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

type Mode = "signIn" | "create";
type How = "google" | "email" | "create";
type Field = "name" | "email" | "password";
type Values = Record<Field, string>;
/** Keys under `landing` that say what is wrong with a field. */
type FieldError =
  | "signIn.emailRequired"
  | "signIn.passwordRequired"
  | "createAccount.nameRequired"
  | "createAccount.emailInvalid"
  | "createAccount.passwordShort";
type FieldErrors = Partial<Record<Field, FieldError>>;

const FIELDS: readonly Field[] = ["name", "email", "password"];
const NO_VALUES: Values = { name: "", email: "", password: "" };

/** What is wrong with the submitted fields. Sign-in only asks that they are filled in. */
export function validate(mode: Mode, v: Values): FieldErrors {
  const errors: FieldErrors = {};
  if (mode === "create" && v.name === "") errors.name = "createAccount.nameRequired";
  if (v.email === "") errors.email = "signIn.emailRequired";
  else if (mode === "create" && !EMAIL_SHAPE.test(v.email)) errors.email = "createAccount.emailInvalid";
  if (v.password === "") errors.password = "signIn.passwordRequired";
  else if (mode === "create" && v.password.length < MIN_PASSWORD_LENGTH)
    errors.password = "createAccount.passwordShort";
  return errors;
}

function readValues(form: HTMLFormElement): Values {
  const data = new FormData(form);
  const text = (field: Field) => String(data.get(field) ?? "");
  return { name: text("name").trim(), email: text("email").trim(), password: text("password") };
}

export function SignInForm() {
  const t = useTranslations("landing");
  const tError = useTranslations("errors");
  const router = useRouter();
  const { signInWithGoogle, signInWithEmail, createAccountWithEmail, status } = useSession();
  // The shell asks for /v1/me next anyway; asking here only moves that one read earlier.
  const me = useMe(status === "signed-in");
  const sent = useRef(false);
  const [mode, setMode] = useState<Mode>("signIn");
  const [busy, setBusy] = useState<How | null>(null);
  const [error, setError] = useState<AuthErrorKey | null>(null);
  // What was wrong with each field on submit: each says so under itself until it is typed in.
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
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

  const go = async (how: How, v: Values = NO_VALUES) => {
    setBusy(how);
    setError(null);
    try {
      if (how === "google") await signInWithGoogle();
      else if (how === "email") await signInWithEmail(v.email, v.password);
      else await createAccountWithEmail(v.name, v.email, v.password);
    } catch (e) {
      if (how === "create") setError(`createAccount.${createAccountMessage(e)}`);
      else {
        const key = signInMessage(how, e);
        setError(key && `signIn.${key}`);
      }
      setBusy(null);
    }
  };

  const switchMode = () => {
    setMode((m) => (m === "signIn" ? "create" : "signIn"));
    setError(null);
    setFieldErrors({});
  };

  const clearFieldError = (field: Field) => setFieldErrors((f) => (f[field] ? { ...f, [field]: undefined } : f));

  const submit = (form: HTMLFormElement) => {
    const values = readValues(form);
    const errors = validate(mode, values);
    setFieldErrors(errors);
    const first = FIELDS.find((f) => errors[f]);
    if (first) {
      form.querySelector<HTMLInputElement>(`input[name="${first}"]`)?.focus();
      return;
    }
    void go(mode === "create" ? "create" : "email", values);
  };

  const creating = mode === "create";
  const fieldText = (field: Field) => {
    const key = fieldErrors[field];
    return key ? t(key) : undefined;
  };
  const submitLabel = creating
    ? t(pressed === "create" ? "createAccount.creating" : "createAccount.submit")
    : t(pressed === "email" ? "signIn.signingIn" : "signIn.submit");

  return (
    <div className="mt-5 space-y-4">
      {env.NEXT_PUBLIC_AUTH_MOCK ? (
        <p className="text-xs text-muted">
          <MockTag /> {t("signIn.mockNote")}
        </p>
      ) : null}
      <Button variant="secondary" className="h-11 w-full" onClick={() => void go("google")} disabled={locked}>
        <GoogleMark />
        {pressed === "google" ? t("signIn.signingIn") : t("signIn.google")}
      </Button>
      <div className="flex items-center gap-3 text-xs text-muted">
        <span className="h-px flex-1 bg-rule" />
        {creating ? t("createAccount.orEmail") : t("signIn.orDemoLogin")}
        <span className="h-px flex-1 bg-rule" />
      </div>
      <form
        className="space-y-4"
        // The form says itself which field is wrong, in the interface language, instead of the browser's tooltip.
        noValidate
        onSubmit={(e) => {
          e.preventDefault();
          submit(e.currentTarget);
        }}
      >
        {creating ? (
          <TextField
            id={`${id}-name`}
            name="name"
            type="text"
            autoComplete="name"
            required
            label={t("createAccount.name")}
            error={fieldText("name")}
            onChange={() => clearFieldError("name")}
          />
        ) : null}
        <TextField
          id={`${id}-email`}
          name="email"
          type="email"
          autoComplete="username"
          inputMode="email"
          spellCheck={false}
          required
          label={t("signIn.email")}
          error={fieldText("email")}
          onChange={() => clearFieldError("email")}
          placeholder={t("signIn.emailPlaceholder")}
        />
        <TextField
          id={`${id}-password`}
          name="password"
          type={showPassword ? "text" : "password"}
          autoComplete={creating ? "new-password" : "current-password"}
          required
          label={t("signIn.password")}
          error={fieldText("password")}
          hint={creating ? t("createAccount.passwordHint") : t("signIn.passwordHint")}
          onChange={() => clearFieldError("password")}
          trailing={
            <button
              type="button"
              aria-pressed={showPassword}
              onClick={() => setShowPassword((v) => !v)}
              className="absolute inset-y-0 right-0 rounded-r-md px-3 text-[13px] font-medium text-muted hover:text-ink"
            >
              {showPassword ? t("signIn.hide") : t("signIn.show")}{" "}
              <span className="sr-only">{t("signIn.passwordSuffix")}</span>
            </button>
          }
        />
        {error ? (
          <p role="alert" className="text-sm text-blocked">
            {tError(error)}
          </p>
        ) : null}
        <Button type="submit" className="h-11 w-full" disabled={locked}>
          {submitLabel}
        </Button>
      </form>
      <p className="text-center text-[13px] text-muted">
        {creating ? t("createAccount.backPrompt") : t("createAccount.switchPrompt")}{" "}
        <button type="button" onClick={switchMode} disabled={locked} className="link font-medium text-ink">
          {creating ? t("createAccount.back") : t("createAccount.switch")}
        </button>
      </p>
      <div className="space-y-1 text-[13px] leading-relaxed text-muted">
        {creating ? (
          // Honest about the unverified address: invitations are only answered for a verified email.
          <p>{t("createAccount.invitationNote")}</p>
        ) : (
          <>
            <p>{t("signIn.joinNoteMember")}</p>
            <p>{t("signIn.joinNoteReviewer")}</p>
          </>
        )}
      </div>
    </div>
  );
}

type TextFieldProps = Omit<ComponentProps<"input">, "id" | "className" | "aria-invalid" | "aria-describedby"> & {
  id: string;
  label: string;
  /** Shown under the field, and read out before the hint. */
  error?: string;
  hint?: string;
  /** Sits inside the field at its right edge, such as the show/hide button. */
  trailing?: ReactNode;
};

function TextField({ id, label, error, hint, trailing, ...input }: TextFieldProps) {
  const describedBy = [error ? `${id}-error` : "", hint ? `${id}-hint` : ""].filter(Boolean).join(" ");
  return (
    <div>
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      <div className="relative mt-1.5">
        <input
          id={id}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy || undefined}
          className={cn(FIELD, trailing && "pr-16")}
          {...input}
        />
        {trailing}
      </div>
      {error ? (
        <p id={`${id}-error`} className="mt-1.5 text-xs text-blocked">
          {error}
        </p>
      ) : null}
      {hint ? (
        <p id={`${id}-hint`} className="mt-1.5 text-xs text-muted">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

function GoogleMark() {
  return (
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
  );
}
