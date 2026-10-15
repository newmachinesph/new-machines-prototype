"use client";

import { useTranslations } from "next-intl";
import { useId, useState } from "react";
import { Checkbox, Modal, ModalClose, useToast } from "@/components/base";
import { Button } from "@/components/ui";
import { cn } from "@/lib/cn";
import { useErrorText } from "@/lib/api/use-error-text";
import type { NetworkProfile } from "@/lib/api/gen/types.gen";
import { useReviewerProfile, useUpdateReviewerProfile } from "@/lib/queries/tasks";

type Fields = { name: string; languages: string[]; skills: string[] };

/** "English, Tagalog" as ["English", "Tagalog"]: trimmed, empty parts dropped. */
export const splitList = (text: string) =>
  text
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);

/** A profile with only a name gives New Machines nothing to match tasks on. */
export const isComplete = (p: Fields) => Boolean(p.name.trim()) && (p.languages.length > 0 || p.skills.length > 0);

function Field({
  label,
  value,
  onChange,
  hint,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  hint?: string;
}) {
  const id = useId();
  const hintId = useId();
  return (
    <div className="text-sm">
      <label htmlFor={id} className="font-medium">
        {label}
      </label>
      <input
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        autoComplete="off"
        aria-describedby={hint ? hintId : undefined}
        className="mt-1.5 h-10 w-full rounded-md border border-grey-300 px-3 text-sm outline-none focus:border-ink"
      />
      {hint ? (
        <p id={hintId} className="mt-1 text-xs text-muted">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

/** The profile form. Mounted fresh each time the dialog opens, so its fields start from the saved profile. */
function ProfileForm({
  initial,
  startsReviewing,
  pending,
  onSave,
}: {
  initial: Fields;
  /** The switch opened this form because a profile is needed first: saving then turns reviewing on. */
  startsReviewing: boolean;
  pending: boolean;
  onSave: (fields: Fields) => void;
}) {
  const t = useTranslations("work.profile");
  const tc = useTranslations("common");
  const [name, setName] = useState(initial.name);
  const [languages, setLanguages] = useState(initial.languages.join(", "));
  const [skills, setSkills] = useState(initial.skills.join(", "));
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (name.trim()) onSave({ name: name.trim(), languages: splitList(languages), skills: splitList(skills) });
      }}
      className="mt-4 space-y-4"
    >
      <Field label={t("name")} value={name} onChange={setName} />
      <Field label={t("languages")} value={languages} onChange={setLanguages} hint={t("languagesHint")} />
      <Field label={t("skills")} value={skills} onChange={setSkills} hint={t("skillsHint")} />
      <div className="flex justify-end gap-2">
        <ModalClose render={<Button variant="ghost" />}>{tc("cancel")}</ModalClose>
        <Button type="submit" disabled={!name.trim() || pending}>
          {t(startsReviewing ? "saveAndStart" : "save")}
        </Button>
      </div>
    </form>
  );
}

/**
 * "Review for the network": the user's own switch and profile. Pay for network reviews is simulated.
 * The switch saves at once when the profile is complete; otherwise it opens the profile form with the
 * switch already on. "Edit profile" opens the same form with the switch as it is.
 */
export function NetworkProfilePanel({ className }: { className?: string }) {
  const t = useTranslations("work.profile");
  const profile = useReviewerProfile().data;
  const update = useUpdateReviewerProfile();
  const toast = useToast();
  const errorText = useErrorText();
  const [open, setOpen] = useState(false);
  const [turningOn, setTurningOn] = useState(false);
  if (!profile) return null;

  const save = (enabled: boolean, fields: Fields) =>
    update.mutate(
      { body: { enabled, ...fields } },
      {
        onSuccess: (saved: NetworkProfile) => {
          toast(saved.enabled === profile.enabled ? t("saved") : saved.enabled ? t("on") : t("off"));
          setOpen(false);
        },
        onError: (e) => toast(t("failed"), errorText(e), "blocked"),
      },
    );
  const current = { name: profile.name, languages: profile.languages, skills: profile.skills };
  const openForm = (on: boolean) => {
    setTurningOn(on);
    setOpen(true);
  };
  const turnOn = () => (isComplete(current) ? save(true, current) : openForm(true));

  return (
    <section className={cn("panel px-4 py-3.5 text-[13px] leading-relaxed text-grey-700", className)}>
      <div className="mb-1 text-sm font-medium text-ink">{t("title")}</div>
      <p className="mb-3">{t("body")}</p>
      <div className="flex min-h-10 items-center">
        <Checkbox checked={profile.enabled} onCheckedChange={(on) => (on ? turnOn() : save(false, current))}>
          {t("toggle")}
        </Checkbox>
      </div>
      {profile.suspended ? <p className="mt-2 text-blocked">{t("suspended")}</p> : null}
      <Button variant="secondary" className="mt-3 h-10 sm:h-8" onClick={() => openForm(false)}>
        {t("edit")}
      </Button>
      <Modal open={open} onOpenChange={setOpen} title={t("formTitle")} description={t("formDescription")}>
        <ProfileForm
          initial={current}
          startsReviewing={turningOn}
          pending={update.isPending}
          onSave={(fields) => save(profile.enabled || turningOn, fields)}
        />
      </Modal>
    </section>
  );
}
