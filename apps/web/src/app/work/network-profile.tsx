"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";
import { Checkbox, Modal, ModalClose, useToast } from "@/components/base";
import { Button } from "@/components/ui";
import { useErrorText } from "@/lib/api/use-error-text";
import { useReviewerProfile, useUpdateReviewerProfile } from "@/lib/queries/tasks";

type Fields = { name: string; languages: string[]; skills: string[] };

/** "English, Tagalog" as ["English", "Tagalog"]: trimmed, empty parts dropped. */
export const splitList = (text: string) =>
  text
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);

function Field({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  return (
    <label className="block text-sm">
      <span className="font-medium">{label}</span>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        autoComplete="off"
        className="mt-1.5 h-10 w-full rounded-md border border-grey-300 px-3 text-sm outline-none focus:border-ink"
      />
    </label>
  );
}

/** "Review for the network": the user's own switch and profile. Pay for network reviews is simulated. */
export function NetworkProfilePanel() {
  const t = useTranslations("work.profile");
  const tc = useTranslations("common");
  const profile = useReviewerProfile().data;
  const update = useUpdateReviewerProfile();
  const toast = useToast();
  const errorText = useErrorText();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [languages, setLanguages] = useState("");
  const [skills, setSkills] = useState("");
  if (!profile) return null;

  const save = (enabled: boolean, fields: Fields) =>
    update.mutate(
      { body: { enabled, ...fields } },
      {
        onSuccess: (saved) => {
          toast(saved.enabled ? t("on") : t("off"));
          setOpen(false);
        },
        onError: (e) => toast(t("failed"), errorText(e), "blocked"),
      },
    );
  const edit = () => {
    setName(profile.name);
    setLanguages(profile.languages.join(", "));
    setSkills(profile.skills.join(", "));
    setOpen(true);
  };
  const current = { name: profile.name, languages: profile.languages, skills: profile.skills };

  return (
    <section className="panel px-4 py-3.5 text-[13px] leading-relaxed text-grey-700">
      <div className="mb-1 text-sm font-medium text-ink">{t("title")}</div>
      <p className="mb-3">{t("body")}</p>
      <Checkbox checked={profile.enabled} onCheckedChange={(on) => (on ? edit() : save(false, current))}>
        {t("toggle")}
      </Checkbox>
      {profile.suspended ? <p className="mt-2 text-blocked">{t("suspended")}</p> : null}
      {profile.enabled ? (
        <button type="button" className="link mt-2 text-xs" onClick={edit}>
          {t("edit")}
        </button>
      ) : null}
      <Modal open={open} onOpenChange={setOpen} title={t("formTitle")} description={t("formDescription")}>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (name.trim())
              save(true, { name: name.trim(), languages: splitList(languages), skills: splitList(skills) });
          }}
          className="mt-4 space-y-4"
        >
          <Field label={t("name")} value={name} onChange={setName} />
          <Field label={t("languages")} value={languages} onChange={setLanguages} placeholder={t("languagesHint")} />
          <Field label={t("skills")} value={skills} onChange={setSkills} placeholder={t("skillsHint")} />
          <div className="flex justify-end gap-2">
            <ModalClose render={<Button variant="ghost" />}>{tc("cancel")}</ModalClose>
            <Button type="submit" disabled={!name.trim() || update.isPending}>
              {t("save")}
            </Button>
          </div>
        </form>
      </Modal>
    </section>
  );
}
