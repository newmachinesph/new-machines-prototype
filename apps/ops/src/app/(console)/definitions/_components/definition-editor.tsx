"use client";

import { Tabs } from "@base-ui/react/tabs";
import { FilePlus } from "lucide-react";
import { type FormEvent, useId, useState } from "react";
import { focusPageHeading, useToast } from "@/components/base";
import { ConfirmAction } from "@/components/confirm-action";
import { ReadOnly } from "@/components/read-only";
import { Button, Callout, Id, Pill } from "@/components/ui";
import { ApiError, type ApiIssue } from "@/lib/api/errors";
import { errorText } from "@/lib/api/error-text";
import type { DefinitionDetail } from "@/lib/api/gen/types.gen";
import { cn } from "@/lib/cn";
import { type DefinitionKind, usePublishDefinition, useValidateDefinition } from "@/lib/queries/definitions";
import { useCanWrite } from "@/lib/queries/ops";
import { KIND_LABEL, mainFileName, markdownPathProblem } from "./definition-logic";
import { DiscardDialog, useLeaveGuard } from "./unsaved-changes";

export type DefinitionDraft = { yaml: string; files: Record<string, string> };

/** The text an edit started from and the latest version at that moment (0: the definition is new). */
type Base = { draft: DefinitionDraft; latest: number };

type Check = { ok: true } | { issues: ApiIssue[] } | { failed: string } | null;

const MAIN = "(main)";
const TEXTAREA =
  "block min-h-[28rem] w-full resize-y rounded-md border border-grey-300 bg-paper px-3 py-2 font-mono text-[13px] leading-5 outline-none focus:border-ink";
const INPUT =
  "block h-9 w-full rounded-md border border-grey-300 bg-paper px-3 font-mono text-[13px] outline-none focus:border-ink aria-[invalid]:border-blocked";

const lineCount = (text: string) => {
  const n = text.split("\n").length;
  return `${n} ${n === 1 ? "line" : "lines"}`;
};

const sameDraft = (a: DefinitionDraft, b: DefinitionDraft) =>
  a.yaml === b.yaml &&
  Object.keys(a.files).length === Object.keys(b.files).length &&
  Object.entries(a.files).every(([path, text]) => b.files[path] === text);

/**
 * The text editor for one definition: the main file plus, for agents, a tab per Markdown file. Validate checks
 * the edit against the latest versions of everything else without saving; Publish asks for a reason and makes
 * the edit the next version (or version 1 of a new definition).
 *
 * Unpublished edits are never replaced from under the person: while the draft differs from where it started,
 * leaving asks first, and a version someone else publishes meanwhile is announced instead of loaded. Publish
 * sends the version the edit started from, so the API refuses it (409 VERSION_CONFLICT) if that is stale.
 */
export function DefinitionEditor({
  kind,
  defKey,
  name,
  initial,
  nextVersion,
  isNew = false,
  onPublished,
}: {
  kind: DefinitionKind;
  defKey: string;
  name: string;
  initial: DefinitionDraft;
  nextVersion: number;
  isNew?: boolean;
  onPublished?: (detail: DefinitionDetail) => void;
}) {
  const canWrite = useCanWrite();
  const toast = useToast();
  const validate = useValidateDefinition();
  const publish = usePublishDefinition();
  const latest = nextVersion - 1;
  const [base, setBase] = useState<Base>({ draft: initial, latest });
  const [draft, setDraft] = useState(initial);
  const [tab, setTab] = useState(MAIN);
  // A check result belongs to the exact draft object it was made for. Every change to the draft (an edit, an
  // added file, a discard, a newer version loaded) makes a new object, so a result for older text never shows,
  // including a validation answer that arrives after the text changed.
  const [result, setResult] = useState<{ for: DefinitionDraft; check: Check } | null>(null);
  const check = result && result.for === draft ? result.check : null;
  // While our own publish is in flight, the cache already holds its result as the latest version.
  const [publishing, setPublishing] = useState(false);
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  const hasMarkdown = kind === "agent";
  const mainName = mainFileName(kind, defKey);
  const dirty = !sameDraft(draft, base.draft);
  const path = { kind, key: defKey };
  const guard = useLeaveGuard(dirty);

  // A newer version arrived (a refetch after someone else published). Load it while there is nothing to lose;
  // with unpublished edits, keep them and say so below.
  const moved = latest !== base.latest || !sameDraft(initial, base.draft);
  if (moved && !dirty) {
    setBase({ draft: initial, latest });
    setDraft(initial);
  }
  const publishedSince = !publishing && moved && dirty && latest > base.latest ? latest : null;

  const change = (next: (d: DefinitionDraft) => DefinitionDraft) => setDraft(next);

  const edit = (file: string, text: string) =>
    change((d) => (file === MAIN ? { ...d, yaml: text } : { ...d, files: { ...d.files, [file]: text } }));

  const restart = (from: Base) => {
    setBase(from);
    setDraft(from.draft);
    setTab(MAIN);
  };

  const runValidate = async () => {
    const sent = draft;
    setResult(null);
    let next: Check;
    try {
      const answer = await validate.mutateAsync({ path, body: { yaml: sent.yaml, files: sent.files } });
      next = answer.ok ? { ok: true } : { issues: answer.errors };
    } catch (e) {
      next = { failed: errorText(e) };
    }
    setResult({ for: sent, check: next });
  };

  const runPublish = async (reason: string) => {
    const sent = draft;
    let detail: DefinitionDetail;
    setPublishing(true);
    try {
      detail = await publish.mutateAsync({
        path,
        body: { yaml: sent.yaml, files: sent.files, reason, baseVersion: base.latest },
      });
    } catch (e) {
      if (e instanceof ApiError && e.issues.length) setResult({ for: sent, check: { issues: e.issues } });
      throw e;
    } finally {
      setPublishing(false);
    }
    // The published text, as the API stores it, is where the next edit starts.
    restart({ draft: { yaml: detail.yaml, files: detail.files }, latest: detail.summary.version });
    toast(isNew ? `${KIND_LABEL[kind]} ${defKey} created` : `${name} published as v${detail.summary.version}`);
    onPublished?.(detail);
    focusPageHeading();
  };

  const publishLabel = isNew ? "Create v1" : "Publish";
  const publishButton = canWrite ? (
    <ConfirmAction
      trigger={<Button>{publishLabel}</Button>}
      title={isNew ? `Create ${KIND_LABEL[kind].toLowerCase()} ${defKey}?` : `Publish ${name} as v${nextVersion}?`}
      consequence={
        isNew
          ? "Creates version 1 from this text. Other definitions can refer to it once it is published."
          : `v${nextVersion} becomes the latest version. Runs that start from now on use it; runs already going keep the version they pinned.`
      }
      confirmLabel={isNew ? "Create v1" : `Publish v${nextVersion}`}
      reasonPlaceholder={isNew ? "New connector for the returns pack" : "Raise the match tolerance to 2 cents"}
      onConfirm={runPublish}
    />
  ) : (
    <ReadOnly>
      <Button disabled>{publishLabel}</Button>
    </ReadOnly>
  );

  const editorFor = (file: string, text: string) => (
    <div>
      <textarea
        aria-label={file === MAIN ? mainName : file}
        value={text}
        onChange={(e) => edit(file, e.target.value)}
        spellCheck={false}
        wrap="off"
        className={TEXTAREA}
      />
      <p className="tnum mt-1 text-xs text-muted">{lineCount(text)}</p>
    </div>
  );

  const files = Object.entries(draft.files);

  return (
    <div className="space-y-4 px-5 py-4">
      {publishedSince ? (
        <Callout
          tone="warn"
          title={`v${publishedSince} was published since you started`}
          action={
            <Button variant="secondary" onClick={() => setConfirmDiscard(true)}>
              Load v{publishedSince}
            </Button>
          }
        >
          Your edit started from v{base.latest}, so publishing it would be refused. Copy what you changed, load v
          {publishedSince}, then apply your changes again.
        </Callout>
      ) : null}
      {hasMarkdown ? (
        <Tabs.Root value={tab} onValueChange={(v) => setTab(String(v))}>
          <div className="flex flex-wrap items-center gap-2">
            <div className="max-w-full overflow-x-auto">
              <Tabs.List className="flex rounded-md border border-rule bg-paper p-0.5" aria-label="Files">
                {[MAIN, ...files.map(([p]) => p)].map((file) => (
                  <Tabs.Tab
                    key={file}
                    value={file}
                    className="flex h-8 items-center rounded-[5px] px-3 font-mono text-[12px] whitespace-nowrap text-grey-700 hover:text-ink data-[active]:bg-grey-100 data-[active]:font-medium data-[active]:text-ink"
                  >
                    {file === MAIN ? mainName : file}
                  </Tabs.Tab>
                ))}
              </Tabs.List>
            </div>
            <AddFile
              existing={files.map(([p]) => p)}
              disabled={!canWrite}
              onAdd={(p) => {
                change((d) => ({ ...d, files: { ...d.files, [p]: "" } }));
                setTab(p);
              }}
            />
          </div>
          <Tabs.Panel value={MAIN} className="mt-3 outline-none">
            {editorFor(MAIN, draft.yaml)}
          </Tabs.Panel>
          {files.map(([file, text]) => (
            <Tabs.Panel key={file} value={file} className="mt-3 outline-none">
              {editorFor(file, text)}
            </Tabs.Panel>
          ))}
        </Tabs.Root>
      ) : (
        editorFor(MAIN, draft.yaml)
      )}

      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="secondary"
          onClick={() => void runValidate()}
          disabled={validate.isPending}
          aria-busy={validate.isPending || undefined}
        >
          Validate
        </Button>
        {publishButton}
        {dirty ? (
          <Button variant="ghost" onClick={() => setConfirmDiscard(true)}>
            Discard changes
          </Button>
        ) : null}
      </div>

      <div aria-live="polite">
        <CheckResult check={check} />
      </div>

      <DiscardDialog
        open={confirmDiscard}
        title={publishedSince ? `Load v${publishedSince} and discard your changes?` : "Discard your changes?"}
        confirmLabel={publishedSince ? `Discard and load v${publishedSince}` : "Discard changes"}
        onConfirm={() => {
          setConfirmDiscard(false);
          restart(publishedSince ? { draft: initial, latest } : base);
        }}
        onCancel={() => setConfirmDiscard(false)}
      >
        {publishedSince
          ? `Your unpublished edits are lost and the editor shows v${publishedSince}.`
          : "Your unpublished edits are lost and the editor goes back to the text you started from."}
      </DiscardDialog>
      <DiscardDialog
        open={guard.pending !== null}
        title="Leave without publishing?"
        confirmLabel="Discard and leave"
        onConfirm={guard.leave}
        onCancel={guard.stay}
      >
        Your edits to {name} are not published. Leaving this page discards them.
      </DiscardDialog>
    </div>
  );
}

function CheckResult({ check }: { check: Check }) {
  if (!check) return null;
  if ("ok" in check) {
    return (
      <p className="flex items-center gap-2 text-sm">
        <Pill tone="ink">Valid</Pill>
        No problems found. Ready to publish.
      </p>
    );
  }
  if ("failed" in check) {
    return (
      // No role="alert": the polite live region around this result already announces it.
      <p className="rounded-md border border-blocked/30 bg-blocked-soft/60 px-3 py-2 text-sm text-blocked">
        {check.failed}
      </p>
    );
  }
  const n = check.issues.length;
  return (
    <div className="rounded-md border border-blocked/30 bg-blocked-soft/40 px-4 py-3">
      <h3 className="text-sm font-semibold text-blocked">
        {n} {n === 1 ? "problem" : "problems"} to fix before publishing
      </h3>
      <ul aria-label="Problems" className="mt-2 space-y-2 text-sm">
        {check.issues.map((issue, i) => (
          <li key={`${issue.kind}/${issue.key}/${issue.path}/${i}`} className="leading-snug">
            <span className="flex flex-wrap items-baseline gap-x-2">
              <Id>
                {issue.kind}/{issue.key}
              </Id>
              <code className="font-mono text-[12px] font-medium">{issue.path}</code>
            </span>
            <span className="block text-grey-700">{issue.message}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** "Add file" for agents: a new Markdown skill, added as an empty tab. Nothing is saved until Publish. */
function AddFile({
  existing,
  disabled,
  onAdd,
}: {
  existing: string[];
  disabled: boolean;
  onAdd: (path: string) => void;
}) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState("");
  const [problem, setProblem] = useState<string | null>(null);

  const button = (
    <Button variant="ghost" disabled={disabled} onClick={() => setOpen(true)}>
      <FilePlus className="size-4" aria-hidden />
      Add file
    </Button>
  );
  if (disabled) return <ReadOnly>{button}</ReadOnly>;
  if (!open) return button;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const path = value.trim();
    const why = markdownPathProblem(path, existing);
    setProblem(why);
    if (why) return;
    onAdd(path);
    setOpen(false);
    setValue("");
  };

  return (
    <form onSubmit={submit} noValidate className="flex flex-wrap items-start gap-2">
      <div className="w-56">
        <label htmlFor={`${id}-path`} className="sr-only">
          New file path
        </label>
        <input
          id={`${id}-path`}
          autoFocus
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="skills/<name>.md"
          aria-invalid={problem ? true : undefined}
          aria-describedby={problem ? `${id}-error` : undefined}
          className={cn(INPUT)}
        />
        {problem ? (
          <p id={`${id}-error`} role="alert" className="mt-1 text-xs text-blocked">
            {problem}
          </p>
        ) : null}
      </div>
      <Button type="submit" variant="secondary">
        Add
      </Button>
      <Button
        variant="ghost"
        onClick={() => {
          setOpen(false);
          setValue("");
          setProblem(null);
        }}
      >
        Cancel
      </Button>
    </form>
  );
}
