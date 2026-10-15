"use client";

import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";
import { Checkbox, Segmented, useToast } from "@/components/base";
import { QueryState } from "@/components/query-state";
import { Skeleton } from "@/components/skeleton";
import { Button, ButtonLink, Callout, EmptyState, Section } from "@/components/ui";
import type { AgentDraft, Palette, SkillDraft, StudioAgent } from "@/lib/api/gen/types.gen";
import { ApiError, type ApiIssue, toApiError } from "@/lib/api/errors";
import { useErrorText } from "@/lib/api/use-error-text";
import { useOrgId } from "@/lib/queries/me";
import { useCreateStudioAgent, useSaveStudioAgent, useStudioAgent, useStudioPalette } from "@/lib/queries/studio";
import { useLeaveGuard } from "@/lib/use-leave-guard";
import { useCanBuild } from "../can-build";

const INPUT =
  "mt-1.5 h-10 w-full rounded-md border border-grey-300 px-3 text-sm outline-none focus:border-ink disabled:bg-grey-50 disabled:text-grey-700 aria-[invalid=true]:border-blocked";
const AREA =
  "mt-1.5 w-full rounded-md border border-grey-300 px-3 py-2 text-sm leading-relaxed outline-none focus:border-ink disabled:bg-grey-50 disabled:text-grey-700 aria-[invalid=true]:border-blocked";
// The API's limits (apps/api/app/models/studio.py AgentDraft).
const MAX_SKILLS = 10;
const MAX_TOOLS = 12;
const MIN_TURNS = 1;
const MAX_TURNS = 20;
const DEFAULT_TURNS = 6;

const BLANK: AgentDraft = {
  name: "",
  summary: "",
  instructions: "",
  modelProfile: "reasoning",
  skills: [],
  tools: [],
  maxTurns: DEFAULT_TURNS,
};

type Profile = NonNullable<AgentDraft["modelProfile"]>;

/** A whole number of turns from what was typed: 1 to 20, the default when the field is empty. */
const clampTurns = (raw: string) => {
  const n = Math.round(Number(raw));
  return Number.isFinite(n) && raw.trim() !== "" ? Math.min(MAX_TURNS, Math.max(MIN_TURNS, n)) : DEFAULT_TURNS;
};

/** An issue's field, from the path as the API sends it (`name`, `tools[0]`, `skills[1].title`, or snake_case). */
const fieldOf = (path: string) =>
  path
    .replace(/^\/+/, "")
    .replace(/\//g, ".")
    .replace(/_([a-z])/g, (_, c: string) => c.toUpperCase());

/** Pack issues grouped by the pack they name: one line per pack, its messages as sent beneath. */
function packsOf(issues: ApiIssue[]): [string, string[]][] {
  const out = new Map<string, string[]>();
  for (const i of issues) if (i.kind === "pack") out.set(i.key, [...(out.get(i.key) ?? []), i.message]);
  return [...out];
}

function FieldError({ id, messages }: { id: string; messages: string[] }) {
  if (!messages.length) return null;
  return (
    <p id={id} className="mt-1 text-xs text-blocked">
      {messages.join(" ")}
    </p>
  );
}

/** A new agent (no key) or the latest version of one the org built. */
export function AgentEditor({ agentKey }: { agentKey?: string }) {
  const t = useTranslations("studioAgents");
  const tStudio = useTranslations("studio");
  const canBuild = useCanBuild();
  const palette = useStudioPalette();
  const agent = useStudioAgent(agentKey);
  const errorText = useErrorText();
  const toast = useToast();
  // Counts explicit reloads. The form is keyed on it, not on the server version, so a background refetch (after
  // its own save, or when someone else saved) never remounts it and never discards unsaved edits.
  const [loads, setLoads] = useState(0);
  // A reload that fails keeps the form as it is: remounting it would put the stale draft back over the edits.
  const reload = () =>
    void agent.refetch().then((r) => {
      if (r.isError) toast(t("reloadFailed"), errorText(r.error), "blocked");
      else setLoads((n) => n + 1);
    });
  const skeleton = <Skeleton className="h-[560px]" />;
  const back = (
    <ButtonLink href="/studio/agents" variant="secondary">
      {t("backToAgents")}
    </ButtonLink>
  );
  // A member can read an agent but not build one, so the new route is a notice, not a form that can only fail.
  if (!agentKey && !canBuild)
    return (
      <Section>
        <EmptyState action={back}>{tStudio("buildersOnly")}</EmptyState>
      </Section>
    );
  if (!agentKey)
    return (
      <QueryState query={palette} skeleton={skeleton}>
        {(p) => <AgentForm initial={BLANK} palette={p} />}
      </QueryState>
    );
  // Another org's key and a missing one answer alike (404), so neither reads as "could not load".
  if (agent.isError && agent.error instanceof ApiError && agent.error.status === 404)
    return (
      <Section>
        <EmptyState action={back}>{t("notYours")}</EmptyState>
      </Section>
    );
  return (
    <QueryState query={agent} skeleton={skeleton}>
      {(a) => (
        <QueryState query={palette} skeleton={skeleton}>
          {(p) => (
            <AgentForm
              key={loads}
              initial={a.draft}
              palette={p}
              agentKey={agentKey}
              version={a.version}
              latest={a.version}
              onReload={reload}
            />
          )}
        </QueryState>
      )}
    </QueryState>
  );
}

function AgentForm({
  initial,
  palette,
  agentKey,
  version,
  latest,
  onReload,
}: {
  initial: AgentDraft;
  palette: Palette;
  agentKey?: string;
  /** The version this form opened on; it moves forward with the form's own saves. */
  version?: number;
  /** The version the cache holds now, which a background refetch can move past `version`. */
  latest?: number;
  onReload?: () => void;
}) {
  const t = useTranslations("studioAgents");
  const tStudio = useTranslations("studio");
  const errorText = useErrorText();
  const toast = useToast();
  const router = useRouter();
  const orgId = useOrgId();
  const fid = useId();
  // Members read an agent but cannot save it; the API would answer 403 (kept below as the backstop).
  const canBuild = useCanBuild();
  const create = useCreateStudioAgent();
  const save = useSaveStudioAgent();
  const [draft, setDraft] = useState<AgentDraft>(initial);
  const [turns, setTurns] = useState(String(initial.maxTurns ?? DEFAULT_TURNS));
  const [base, setBase] = useState(version);
  // The draft as last saved (the body that was sent), so an edit made while a save is pending stays unsaved.
  const [saved, setSaved] = useState(() => JSON.stringify(initial));
  const [issues, setIssues] = useState<ApiIssue[]>([]);
  // The API's detail when a save met a newer version (409 VERSION_CONFLICT).
  const [conflict, setConflict] = useState<string | null>(null);
  // Tool issues by the tool's ref, resolved from the list as it was submitted, so they stay with their tool when
  // a tick or untick shifts the indices.
  const [toolErrors, setToolErrors] = useState<Record<string, string[]>>({});
  const dirty = JSON.stringify(draft) !== saved;
  useLeaveGuard(dirty);
  // Our words after a refused save (the API's detail goes beneath), or an early notice when a refetch shows someone
  // else saved since.
  const conflictText =
    conflict !== null
      ? t("conflictSaved")
      : latest !== undefined && base !== undefined && latest > base
        ? t("conflictBody", { n: latest })
        : null;
  // Client-only ids keep each skill's row (and its focus) with its values when one in the middle is removed.
  const [skillIds, setSkillIds] = useState(() => (initial.skills ?? []).map((_, i) => i));
  const nextSkillId = useRef(skillIds.length);
  // The skill whose title should take focus once its row exists (set by Add, read after the next render).
  const pendingFocus = useRef<number | null>(null);
  const skillTitleRefs = useRef(new Map<number, HTMLInputElement>());
  const skillsHeading = useRef<HTMLHeadingElement>(null);

  const reads = palette.tools.filter((tool) => tool.actionClass === "read");
  const skills = draft.skills ?? [];
  const tools = draft.tools ?? [];
  // A chosen tool the registry no longer offers for reading still needs a box, so it can be removed.
  const stale = tools.filter((ref) => !reads.some((tool) => tool.ref === ref));
  const atCap = tools.length >= MAX_TOOLS;
  const pending = create.isPending || save.isPending;
  const set = (patch: Partial<AgentDraft>) => setDraft((d) => ({ ...d, ...patch }));

  const fieldIssues = issues.filter((i) => i.kind !== "pack");
  const packIssues = packsOf(issues);
  const errorsAt = (field: string) => {
    const messages = fieldIssues.filter((i) => fieldOf(i.path) === field).map((i) => i.message);
    return { messages, id: `${fid}-${field.replace(/[^a-zA-Z0-9]+/g, "-")}-error` };
  };
  const toolErrorsAt = (ref: string) => ({
    messages: toolErrors[ref] ?? [],
    id: `${fid}-tool-${ref.replace(/[^a-zA-Z0-9]+/g, "-")}-error`,
  });
  const describe = (e: ReturnType<typeof errorsAt>, ...also: string[]) => ({
    "aria-invalid": e.messages.length ? true : undefined,
    "aria-describedby": [...also, ...(e.messages.length ? [e.id] : [])].join(" ") || undefined,
  });
  const nameErr = errorsAt("name");
  const summaryErr = errorsAt("summary");
  const instructionsErr = errorsAt("instructions");
  const modelErr = errorsAt("modelProfile");
  const turnsErr = errorsAt("maxTurns");
  const toolsErr = errorsAt("tools");
  const turnsHelpId = `${fid}-turns-help`;

  useEffect(() => {
    const id = pendingFocus.current;
    if (id === null) return;
    pendingFocus.current = null;
    skillTitleRefs.current.get(id)?.focus();
  }, [skillIds]);

  const addSkill = () => {
    const id = nextSkillId.current++;
    setSkillIds([...skillIds, id]);
    set({ skills: [...skills, { title: "", text: "" }] });
    pendingFocus.current = id;
  };
  const removeSkill = (i: number) => {
    setSkillIds(skillIds.filter((_, j) => j !== i));
    set({ skills: skills.filter((_, j) => j !== i) });
    // The button that had focus is gone; the section heading is the nearest thing that stays.
    skillsHeading.current?.focus();
  };
  const setSkill = (i: number, patch: Partial<SkillDraft>) =>
    set({ skills: skills.map((x, j) => (j === i ? { ...x, ...patch } : x)) });
  const setTool = (ref: string, on: boolean) =>
    set({ tools: on ? [...tools, ref] : tools.filter((other) => other !== ref) });
  const settleTurns = () => {
    const n = clampTurns(turns);
    setTurns(String(n));
    set({ maxTurns: n });
    return n;
  };

  const onSaved = (sent: AgentDraft) => (a: StudioAgent) => {
    setBase(a.version);
    setSaved(JSON.stringify(sent));
    setConflict(null);
    toast(t("saved"), t("savedVersion", { n: a.version }));
    if (!agentKey) router.replace(`/studio/agents/${a.key}`);
  };
  const onError = (submitted: string[]) => (e: unknown) => {
    const err = toApiError(e);
    if (err.status === 422 && err.issues.length) {
      setIssues(err.issues);
      const byRef: Record<string, string[]> = {};
      for (const i of err.issues) {
        const ref = i.kind !== "pack" ? submitted[Number(/^tools\[(\d+)\]$/.exec(i.path)?.[1] ?? -1)] : undefined;
        if (ref) byRef[ref] = [...(byRef[ref] ?? []), i.message];
      }
      setToolErrors(byRef);
      return;
    }
    // Someone saved since this version was opened: the API's words stay on the page until the latest is loaded.
    if (err.status === 409 && err.code === "VERSION_CONFLICT") {
      setConflict(err.detail);
      return;
    }
    // Building needs the owner or admin role; the API's own wording names the rule, not the person.
    toast(t("saveFailed"), err.status === 403 ? t("notAllowed") : errorText(err), "blocked");
  };
  const submit = () => {
    if (!orgId) return;
    setIssues([]);
    setToolErrors({});
    const body = { ...draft, maxTurns: settleTurns() };
    const handlers = { onSuccess: onSaved(body), onError: onError(body.tools ?? []) };
    if (agentKey)
      save.mutate({ path: { org_id: orgId, key: agentKey }, body: { draft: body, baseVersion: base } }, handlers);
    else create.mutate({ path: { org_id: orgId }, body }, handlers);
  };

  return (
    <form
      className="space-y-5"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      {conflictText ? (
        <Callout
          tone="warn"
          title={t("conflictTitle")}
          action={
            onReload ? (
              <Button variant="secondary" onClick={onReload}>
                {t("reload")}
              </Button>
            ) : undefined
          }
        >
          {conflictText}
          {conflict ? <span className="mt-1 block text-muted">{conflict}</span> : null}
        </Callout>
      ) : null}
      {issues.length ? (
        // Every message is listed once, under its pack or on its own, so the count is the number of messages.
        <Callout tone="blocked" title={t("problems", { n: issues.length })}>
          <ul className="list-disc space-y-1 pl-5 text-sm">
            {fieldIssues.map((i, n) => (
              <li key={`f${n}`}>{i.message}</li>
            ))}
            {packIssues.map(([name, messages]) => (
              <li key={`p-${name}`}>
                {t("packIssue", { name })}
                <ul className="mt-1 list-[circle] space-y-0.5 pl-5">
                  {messages.map((m, j) => (
                    <li key={j}>{m}</li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        </Callout>
      ) : null}
      {/* One switch makes every native field inside read-only for a member; Base UI controls get it by prop. */}
      {/* Locked while a new agent is created: the page moves to it on success, without anything typed meanwhile. */}
      <fieldset disabled={!canBuild || create.isPending} className="min-w-0 space-y-5">
        <Section title={t("about")}>
          <div className="grid gap-4 p-5">
            <div>
              <label className="text-sm font-medium">
                {t("name")}
                <input
                  className={INPUT}
                  value={draft.name}
                  maxLength={80}
                  required
                  onChange={(e) => set({ name: e.target.value })}
                  {...describe(nameErr)}
                />
              </label>
              <FieldError {...nameErr} />
            </div>
            <div>
              <label className="text-sm font-medium">
                {t("summary")}
                <input
                  className={INPUT}
                  value={draft.summary}
                  maxLength={280}
                  required
                  onChange={(e) => set({ summary: e.target.value })}
                  {...describe(summaryErr)}
                />
              </label>
              <FieldError {...summaryErr} />
            </div>
            <div>
              <label className="text-sm font-medium">
                {t("instructions")}
                <textarea
                  className={AREA}
                  rows={8}
                  value={draft.instructions}
                  maxLength={12000}
                  required
                  onChange={(e) => set({ instructions: e.target.value })}
                  {...describe(instructionsErr)}
                />
              </label>
              <FieldError {...instructionsErr} />
            </div>
            <div>
              <p className="text-sm font-medium">{t("model")}</p>
              <div className="mt-1.5">
                <Segmented<Profile>
                  label={t("model")}
                  value={draft.modelProfile ?? "reasoning"}
                  disabled={!canBuild}
                  onValueChange={(v) => set({ modelProfile: v })}
                  options={[
                    { value: "reasoning", label: t("reasoning") },
                    { value: "fast", label: t("fast") },
                  ]}
                />
              </div>
              <FieldError {...modelErr} />
            </div>
            <div>
              <label className="text-sm font-medium">
                {t("maxTurns")}
                <input
                  type="number"
                  inputMode="numeric"
                  className={`${INPUT} max-w-32`}
                  min={MIN_TURNS}
                  max={MAX_TURNS}
                  step={1}
                  value={turns}
                  onChange={(e) => setTurns(e.target.value)}
                  onBlur={settleTurns}
                  {...describe(turnsErr, turnsHelpId)}
                />
              </label>
              <p id={turnsHelpId} className="mt-1 text-xs text-muted">
                {t("maxTurnsHelp", { n: DEFAULT_TURNS })}
              </p>
              <FieldError {...turnsErr} />
            </div>
          </div>
        </Section>

        <Section title={t("tools")}>
          <div className="space-y-3 p-5">
            <p className="text-sm text-muted">
              {t("toolsHelp")} {t("toolsMax", { n: MAX_TOOLS })}
            </p>
            <FieldError {...toolsErr} />
            {reads.map((tool) => {
              const checked = tools.includes(tool.ref);
              const err = toolErrorsAt(tool.ref);
              return (
                <div key={tool.ref}>
                  <Checkbox
                    checked={checked}
                    disabled={!canBuild || (atCap && !checked)}
                    invalid={err.messages.length > 0}
                    describedBy={err.messages.length ? err.id : undefined}
                    onCheckedChange={(on) => setTool(tool.ref, on)}
                  >
                    <span className="font-medium">
                      {tool.app}: {tool.name}
                    </span>
                    <span className="block text-xs text-muted">{tool.description}</span>
                  </Checkbox>
                  <FieldError {...err} />
                </div>
              );
            })}
            {stale.map((ref) => {
              const err = toolErrorsAt(ref);
              return (
                <div key={ref}>
                  <Checkbox
                    checked
                    disabled={!canBuild}
                    invalid={err.messages.length > 0}
                    describedBy={err.messages.length ? err.id : undefined}
                    onCheckedChange={(on) => setTool(ref, on)}
                  >
                    <span className="font-mono text-[13px] font-medium">{ref}</span>
                    <span className="block text-xs text-muted">{t("toolGone")}</span>
                  </Checkbox>
                  <FieldError {...err} />
                </div>
              );
            })}
          </div>
        </Section>

        <Section
          title={t("skills")}
          headingRef={skillsHeading}
          aside={
            canBuild ? (
              <Button variant="secondary" className="h-8" disabled={skills.length >= MAX_SKILLS} onClick={addSkill}>
                {t("addSkill")}
              </Button>
            ) : null
          }
        >
          <div className="space-y-4 p-5">
            {skills.length === 0 ? <p className="text-sm text-muted">{t("noSkills")}</p> : null}
            {skills.map((s, i) => {
              const id = skillIds[i];
              const titleErr = errorsAt(`skills[${i}].title`);
              const textErr = errorsAt(`skills[${i}].text`);
              return (
                <div key={id} className="space-y-2 rounded-md border border-rule p-3">
                  <div>
                    <label className="block text-sm font-medium">
                      {t("skillTitle", { n: i + 1 })}
                      <input
                        ref={(el) => {
                          if (el) skillTitleRefs.current.set(id, el);
                          else skillTitleRefs.current.delete(id);
                        }}
                        className={INPUT}
                        value={s.title}
                        maxLength={80}
                        required
                        onChange={(e) => setSkill(i, { title: e.target.value })}
                        {...describe(titleErr)}
                      />
                    </label>
                    <FieldError {...titleErr} />
                  </div>
                  <div>
                    <label className="block text-sm font-medium">
                      {t("skillText", { n: i + 1 })}
                      <textarea
                        className={AREA}
                        rows={4}
                        value={s.text}
                        maxLength={8000}
                        required
                        onChange={(e) => setSkill(i, { text: e.target.value })}
                        {...describe(textErr)}
                      />
                    </label>
                    <FieldError {...textErr} />
                  </div>
                  {canBuild ? (
                    <Button variant="ghost" className="h-8" onClick={() => removeSkill(i)}>
                      {t("removeSkill", { n: i + 1 })}
                    </Button>
                  ) : null}
                </div>
              );
            })}
          </div>
        </Section>
      </fieldset>

      <div className="flex items-center gap-3">
        {canBuild ? (
          <Button type="submit" disabled={pending || !orgId}>
            {t("save")}
          </Button>
        ) : (
          <p className="text-sm text-muted">{tStudio("buildersOnly")}</p>
        )}
        {base ? <span className="text-sm text-muted">{t("version", { n: base })}</span> : null}
        {dirty ? <span className="text-sm text-muted">{t("unsaved")}</span> : null}
      </div>
    </form>
  );
}
