"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";
import { Modal, Segmented, useToast } from "@/components/base";
import { Skeleton } from "@/components/skeleton";
import { Button, Callout } from "@/components/ui";
import type { BuilderIssue } from "@/lib/api/gen/types.gen";
import { useErrorText } from "@/lib/api/use-error-text";
import { useEditor, useEditorApi } from "@/lib/builder/store";
import { useOrgId } from "@/lib/queries/me";
import { useImportStudioWorkflow, useStudioPackWorkflow } from "@/lib/queries/studio";

type Tab = "export" | "import";

/**
 * The pack as workflow.yaml. Export shows the saved version. Import sends YAML to the API, which parses it (the
 * browser has no YAML library), and puts the steps it returns on the canvas; undo brings the old ones back.
 * A member only exports: the import tab is for those who can build. The export query is handled here, never
 * thrown to the route's error panel, so a failed fetch cannot replace the editor and lose the unsaved canvas.
 */
export function YamlDialog({
  packKey,
  dirty,
  readOnly = false,
  onImported,
}: {
  packKey?: string;
  dirty: boolean;
  readOnly?: boolean;
  /** The problems the API found in an import, after its steps are on the canvas. */
  onImported?: (issues: BuilderIssue[]) => void;
}) {
  const t = useTranslations("studioYaml");
  const toast = useToast();
  const errorText = useErrorText();
  const orgId = useOrgId();
  const api = useEditorApi();
  const [open, setOpen] = useState(false);
  const [chosen, setChosen] = useState<Tab>(packKey ? "export" : "import");
  const tab: Tab = readOnly ? "export" : chosen;
  const [text, setText] = useState("");
  const [issues, setIssues] = useState<BuilderIssue[]>([]);
  // The last import came back without a start step, so the canvas was left alone.
  const [noStart, setNoStart] = useState(false);
  // How long the history was once the import was on the canvas. Undoing the import takes its steps off the
  // canvas, and what could not be read about them goes with them, for good: an edit made after the undo would
  // make the history as long again without putting the steps back.
  const [importedAt, setImportedAt] = useState<number | null>(null);
  const past = useEditor((s) => s.history.past.length);
  if (importedAt !== null && past < importedAt) {
    setIssues([]);
    setImportedAt(null);
  }
  const exported = useStudioPackWorkflow(packKey, open && tab === "export");
  const importer = useImportStudioWorkflow();

  const copy = (yaml: string) => {
    // No clipboard on an insecure origin: say so rather than do nothing.
    if (!navigator.clipboard) {
      toast(t("copyFailed"), undefined, "blocked");
      return;
    }
    void navigator.clipboard.writeText(yaml).then(
      () => toast(t("copied")),
      () => toast(t("copyFailed"), undefined, "blocked"),
    );
  };

  const onImport = () => {
    if (!orgId || !text.trim()) return;
    setNoStart(false);
    importer.mutate(
      { path: { org_id: orgId }, body: { yaml: text } },
      {
        onSuccess: (w) => {
          // A pack has exactly one start and the palette cannot add one, so steps without a start (the start was
          // the unreadable one, or nothing was readable) would leave a canvas only undo could mend: they stay off it.
          const hasStart = w.steps.some((s) => s.type === "trigger");
          setIssues(w.issues);
          setNoStart(!hasStart);
          setImportedAt(null);
          if (!hasStart) return;
          api.getState().replaceGraph(w.steps);
          setImportedAt(api.getState().history.past.length);
          onImported?.(w.issues);
          toast(t("imported"), t("importedBody", { n: w.steps.length }));
          if (!w.issues.length) setOpen(false);
        },
        onError: (e) => toast(t("importFailed"), errorText(e), "blocked"),
      },
    );
  };

  const exportTab = !packKey ? (
    <p className="text-sm text-muted">{t("saveFirst")}</p>
  ) : exported.isPending ? (
    <Skeleton className="h-72" />
  ) : exported.isError && exported.data === undefined ? (
    <Callout tone="blocked" title={t("exportFailed")}>
      {errorText(exported.error)}
    </Callout>
  ) : (
    <div className="space-y-2">
      {dirty ? <p className="text-xs text-human">{t("savedOnly")}</p> : null}
      <textarea
        readOnly
        aria-label={t("exportLabel")}
        value={exported.data?.yaml ?? ""}
        className="h-72 w-full rounded-md border border-rule bg-grey-50 p-3 font-mono text-[12px] leading-relaxed"
      />
      <Button variant="secondary" onClick={() => copy(exported.data?.yaml ?? "")}>
        {t("copy")}
      </Button>
    </div>
  );

  const importTab = (
    <div className="space-y-2">
      <label className="block text-sm font-medium">
        {t("importLabel")}
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          className="mt-1.5 h-60 w-full rounded-md border border-grey-300 p-3 font-mono text-[12px] outline-none focus:border-ink"
        />
      </label>
      <p className="text-xs text-muted">{t("importNote")}</p>
      {noStart || issues.length ? (
        <Callout tone="warn" title={noStart ? t("noStartTitle") : t("importIssues", { n: issues.length })}>
          {noStart ? <p>{t("noStart")}</p> : null}
          {issues.length ? (
            <ul className="list-disc space-y-1 pl-5">
              {issues.map((i, n) => (
                <li key={n}>{i.message}</li>
              ))}
            </ul>
          ) : null}
        </Callout>
      ) : null}
      <Button onClick={onImport} disabled={importer.isPending || !text.trim()}>
        {t("importButton")}
      </Button>
    </div>
  );

  return (
    <Modal
      open={open}
      onOpenChange={setOpen}
      trigger={<Button variant="secondary">{t("open")}</Button>}
      title={t("title")}
      description={t("lede")}
      className="w-[min(760px,calc(100vw-2rem))]"
    >
      <div className="mt-4 space-y-3">
        {readOnly ? null : (
          <Segmented
            label={t("title")}
            value={tab}
            onValueChange={setChosen}
            options={[
              { value: "export", label: t("export") },
              { value: "import", label: t("import") },
            ]}
          />
        )}
        {tab === "export" ? exportTab : importTab}
      </div>
    </Modal>
  );
}
