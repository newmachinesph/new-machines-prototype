"use client";

import { ReactFlowProvider, useReactFlow } from "@xyflow/react";
import { Redo2, Undo2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { useShallow } from "zustand/react/shallow";
import { Segmented, useToast } from "@/components/base";
import { QueryState } from "@/components/query-state";
import { Skeleton } from "@/components/skeleton";
import { Button, ButtonLink, Callout, EmptyState, Section } from "@/components/ui";
import type { BuilderIssue, PackCopy, PackDraft, Palette, StudioPack } from "@/lib/api/gen/types.gen";
import { ApiError, toApiError } from "@/lib/api/errors";
import { useErrorText } from "@/lib/api/use-error-text";
import { blocksRequest, detailsIssues, type DetailsIssue, type EditorIssue } from "@/lib/builder/details";
import { graphIssues } from "@/lib/builder/rules";
import { createEditorStore, draftOf, EditorStoreContext, useEditor, useEditorApi } from "@/lib/builder/store";
import { starterPack } from "@/lib/builder/template";
import { useOrgId } from "@/lib/queries/me";
import {
  useCreateStudioPack,
  useSaveStudioPack,
  useStudioPack,
  useStudioPackCopy,
  useStudioPalette,
  useValidateStudioPack,
} from "@/lib/queries/studio";
import { useLeaveGuard } from "@/lib/use-leave-guard";
import { useCanBuild } from "../../can-build";
import { SubmitButton } from "../../submit-dialog";
import { DetailsForm, type DetailsFocus } from "./details-form";
import { EditorCanvas } from "./editor-canvas";
import { countByStep, isDetailsIssue, IssuesPanel, type ServerIssue } from "./issues-panel";
import { PalettePanel } from "./palette-panel";
import { ReadOnlyContext } from "./read-only";
import { StepList } from "./step-list";
import { StepIssuesContext } from "./step-node";
import { StepSettings } from "./step-settings";
import { TestDialog } from "./test-dialog";
import { useMatches } from "@/lib/use-matches";
import { YamlDialog } from "./yaml-dialog";

const NO_ISSUES: ServerIssue[] = [];
/** The statuses of a copy the API refuses on purpose: not found, not copyable, not editable. */
const REFUSED_COPY = new Set([404, 409, 422]);
// Tailwind's md: below it the canvas is left out and the panels stack.
const CANVAS_QUERY = "(min-width: 48rem)";

function useStarter(): PackDraft {
  const t = useTranslations("studioEditor");
  return starterPack({
    name: t("starter.name"),
    outcome: t("starter.outcome"),
    description: t("starter.description"),
    humanReview: t("starter.humanReview"),
    inputLabel: t("starter.inputLabel"),
    reviewTitle: t("starter.reviewTitle"),
    reviewInstructions: t("starter.reviewInstructions"),
  });
}

/** What a copy kept and could not carry over, above the editor that opened on it. */
function CopyBanner({ copy }: { copy: PackCopy }) {
  const t = useTranslations("studioPacks");
  return (
    <Callout tone="info" title={t("copyBanner", { name: copy.source.name })}>
      <p>{t("copyKeeps")}</p>
      {copy.issues.length ? (
        <ul className="mt-2 list-disc pl-5">
          {copy.issues.map((i) => (
            <li key={`${i.path}:${i.message}`}>{i.message}</li>
          ))}
        </ul>
      ) : null}
    </Callout>
  );
}

/** A new pack (no key), a copy of another (`from`), or the latest version of one the org built, in the editor. */
export function PackEditor({ packKey, from }: { packKey?: string; from?: string }) {
  const t = useTranslations("studioPacks");
  const tEditor = useTranslations("studioEditor");
  const tStudio = useTranslations("studio");
  const canBuild = useCanBuild();
  const palette = useStudioPalette();
  const pack = useStudioPack(packKey);
  const copy = useStudioPackCopy(packKey ? undefined : from);
  const starter = useStarter();
  const errorText = useErrorText();
  const toast = useToast();
  // Counts explicit reloads. The editor is keyed on it, not on the server version, so a background refetch (after
  // its own save, or when someone else saved) never remounts it and never discards the canvas or its history.
  const [loads, setLoads] = useState(0);
  // A reload that fails keeps the editor as it is: remounting it would put the stale draft back over the edits.
  const reload = () =>
    void pack.refetch().then((r) => {
      if (r.isError) toast(tEditor("reloadFailed"), errorText(r.error), "blocked");
      else setLoads((n) => n + 1);
    });
  const skeleton = <Skeleton className="h-[680px]" />;
  const back = (
    <ButtonLink href="/studio/packs" variant="secondary">
      {t("backToPacks")}
    </ButtonLink>
  );
  // A member can read a pack but not build one, so the new route is a notice, not an editor that can only fail.
  if (!packKey && !canBuild)
    return (
      <Section>
        <EmptyState action={back}>{tStudio("buildersOnly")}</EmptyState>
      </Section>
    );
  if (!packKey && from) {
    // A copy the API refuses (an unknown key, another publisher's pack, a pack the Studio cannot open) is a
    // notice with the API's words; any other failure (offline, 5xx) goes to QueryState and its retry.
    if (
      copy.isError &&
      copy.data === undefined &&
      copy.error instanceof ApiError &&
      REFUSED_COPY.has(copy.error.status)
    )
      return (
        <Section>
          <EmptyState
            action={
              <ButtonLink href="/app/marketplace" variant="secondary">
                {t("backToMarketplace")}
              </ButtonLink>
            }
          >
            {errorText(copy.error)}
          </EmptyState>
        </Section>
      );
    return (
      <QueryState query={copy} skeleton={skeleton}>
        {(c) => (
          <QueryState query={palette} skeleton={skeleton}>
            {(p) => (
              <>
                <div className="mb-4">
                  <CopyBanner copy={c} />
                </div>
                <Editor initial={c.draft} palette={p} />
              </>
            )}
          </QueryState>
        )}
      </QueryState>
    );
  }
  if (!packKey)
    return (
      <QueryState query={palette} skeleton={skeleton}>
        {(p) => <Editor initial={starter} palette={p} />}
      </QueryState>
    );
  // Another org's key and a missing one answer alike (404), so neither reads as "could not load". A background
  // refetch that fails keeps the open editor, as QueryState does: only a 404 with nothing loaded is the notice.
  if (pack.isError && pack.data === undefined && pack.error instanceof ApiError && pack.error.status === 404)
    return (
      <Section>
        <EmptyState action={back}>{t("notYours")}</EmptyState>
      </Section>
    );
  return (
    <QueryState query={pack} skeleton={skeleton}>
      {(found) => (
        <QueryState query={palette} skeleton={skeleton}>
          {(p) => (
            <Editor
              key={loads}
              initial={found.draft}
              palette={p}
              packKey={packKey}
              version={found.version}
              latest={found.version}
              onReload={reload}
            />
          )}
        </QueryState>
      )}
    </QueryState>
  );
}

type EditorProps = {
  packKey?: string;
  /** The version the editor opened on; it moves forward with the editor's own saves. */
  version?: number;
  /** The version the cache holds now, which a background refetch can move past `version`. */
  latest?: number;
  onReload?: () => void;
};

/** One store per open pack, made once: a refetched pack after a save does not reset the canvas or its history. */
function Editor({ initial, palette, ...rest }: EditorProps & { initial: PackDraft; palette: Palette }) {
  const [store] = useState(() => createEditorStore({ draft: initial, palette }));
  return (
    <EditorStoreContext.Provider value={store}>
      <ReactFlowProvider>
        <Workbench {...rest} />
      </ReactFlowProvider>
    </EditorStoreContext.Provider>
  );
}

function Workbench({ packKey, version, latest, onReload }: EditorProps) {
  const t = useTranslations("studioEditor");
  const tStudio = useTranslations("studio");
  const toast = useToast();
  const router = useRouter();
  const orgId = useOrgId();
  // Members read a pack but cannot save it; the API would answer 403 (kept as the backstop).
  const canBuild = useCanBuild();
  const errorText = useErrorText();
  const create = useCreateStudioPack();
  const save = useSaveStudioPack();
  const validate = useValidateStudioPack();
  const api = useEditorApi();
  const { fitView } = useReactFlow();
  const { nodes, edges, details, palette, tools, selectedId, canUndo, canRedo } = useEditor(
    useShallow((s) => ({
      nodes: s.nodes,
      edges: s.edges,
      details: s.details,
      palette: s.palette,
      tools: s.tools,
      selectedId: s.selectedId,
      canUndo: s.history.past.length > 0,
      canRedo: s.history.future.length > 0,
    })),
  );
  const draftJson = useMemo(() => JSON.stringify(draftOf({ nodes, edges, details })), [nodes, edges, details]);
  // A new pack is unsaved until it is created.
  const [savedJson, setSavedJson] = useState(() => (packKey ? JSON.stringify(draftOf(api.getState())) : ""));
  // What leaving would lose: a new pack nobody has touched yet loses nothing.
  const [openedJson] = useState(() => JSON.stringify(draftOf(api.getState())));
  const [base, setBase] = useState(version);
  // The API's answer about one exact draft: it stops applying as soon as the draft changes. An import's
  // issues are about the draft too, but the import did not check the whole draft (`imported`).
  const [server, setServer] = useState<{ json: string; issues: ServerIssue[]; imported?: boolean } | null>(null);
  // The API's words when a rename met runs in progress (409 RUNS_IN_PROGRESS), kept while that name stands.
  const [held, setHeld] = useState<{ detail: string; name: string } | null>(null);
  // The API's detail when a save met a newer version (409 VERSION_CONFLICT), kept until the latest is loaded.
  const [conflict, setConflict] = useState<string | null>(null);
  // The details input an issue picked under the canvas asks for; cleared once used, so it is never replayed.
  const [focus, setFocus] = useState<DetailsFocus | null>(null);
  const focused = useCallback(() => setFocus(null), []);
  const [panel, setPanel] = useState<"steps" | "add">("steps");
  // Where focus goes when the control that had it disappears (Remove, the Pack details button).
  const panelHeading = useRef<HTMLHeadingElement>(null);
  const saveHintId = useId();
  // A phone gets the step list and the settings, not a canvas too small to work on. The list, the outcome
  // choices in the settings and undo cover every edit; positions are not part of the saved pack.
  const withCanvas = useMatches(CANVAS_QUERY);
  const dirty = draftJson !== savedJson;
  // A saved pack with nothing changed has nothing to save; the reason is read with the button, not only seen.
  const noChanges = !!packKey && !dirty;
  // When the panels stack with no canvas (a phone), the settings are below the fold: choosing a step in the list
  // brings them into view. With a canvas, selecting or dragging a node must not scroll the canvas away.
  useEffect(() => {
    if (!selectedId || withCanvas) return;
    panelHeading.current?.scrollIntoView?.({ block: "start" });
  }, [selectedId, withCanvas]);
  useLeaveGuard(draftJson !== (savedJson || openedJson));
  // While a new pack is being created, the editor is locked: the page moves to the saved pack on success, and an
  // edit made in between would not be in it.
  const locked = !canBuild || create.isPending;
  // Our words after a refused save (the API's detail goes beneath), or an early notice when a refetch shows someone
  // else saved since. Saving an agent rebuilds the packs that use it, so this is not rare.
  const conflictText =
    conflict !== null
      ? t("conflictSaved")
      : latest !== undefined && base !== undefined && latest > base
        ? t("conflictBody", { n: latest })
        : null;
  const checked = server?.json === draftJson && !server.imported;
  const current = useMemo(() => (server && server.json === draftJson ? server.issues : NO_ISSUES), [server, draftJson]);
  const local = useMemo<EditorIssue[]>(
    () => [...detailsIssues(details), ...graphIssues(nodes, edges, tools, palette)],
    [details, nodes, edges, tools, palette],
  );
  const counts = useMemo(() => countByStep(local, current), [local, current]);
  // Pack names are unique in the org: the API's objection to the name belongs on the name field (path `name`).
  const nameErrors = useMemo(
    () => current.filter((i) => !i.step && i.path === "name").map((i) => i.message),
    [current],
  );
  const blocked = blocksRequest(local);
  const detailProblems = useMemo(() => local.filter(isDetailsIssue), [local]);
  const heldDetail = held && held.name === details.name ? held.detail : null;

  const pick = (step: string) => {
    api.getState().select(step);
    void fitView({ nodes: [{ id: step }], maxZoom: 1, duration: 200 });
  };
  const pickDetails = (issue?: DetailsIssue) => {
    api.getState().select(null);
    if (issue) setFocus((f) => ({ issue, n: (f?.n ?? 0) + 1 }));
    // From the Pack details button, which goes away with the step: the heading keeps the place.
    else panelHeading.current?.focus();
  };

  const refused = (json: string, name: string) => (e: unknown) => {
    const err = toApiError(e);
    if (err.status === 422 && err.issues.length) {
      setServer({
        json,
        issues: err.issues.map((i) => ({ step: i.key || undefined, path: i.path, message: i.message })),
      });
      toast(t("notSaved"), t("seeProblems"), "blocked");
    } else if (err.code === "VERSION_CONFLICT") setConflict(err.detail);
    else if (err.code === "RUNS_IN_PROGRESS") setHeld({ detail: err.detail, name });
    else toast(t("notSaved"), errorText(err), "blocked");
  };

  const onSave = () => {
    if (!orgId) return;
    // The request check would refuse the body before sending it, with nothing to show: say so here instead.
    if (blocked) {
      toast(t("notSaved"), t("fixFirst"), "blocked");
      return;
    }
    setHeld(null);
    const body = draftOf(api.getState());
    const json = JSON.stringify(body);
    const onSuccess = (p: StudioPack) => {
      setBase(p.version);
      setSavedJson(json);
      setConflict(null);
      setServer({ json, issues: [] });
      toast(t("saved"), t("savedVersion", { n: p.version }));
      if (!packKey) router.replace(`/studio/packs/${p.key}`);
    };
    const onError = refused(json, body.name);
    if (packKey)
      save.mutate(
        { path: { org_id: orgId, key: packKey }, body: { draft: body, baseVersion: base } },
        { onSuccess, onError },
      );
    else create.mutate({ path: { org_id: orgId }, body }, { onSuccess, onError });
  };

  const onValidate = () => {
    if (!orgId) return;
    if (blocked) {
      toast(t("notChecked"), t("fixFirst"), "blocked");
      return;
    }
    const body = draftOf(api.getState());
    const json = JSON.stringify(body);
    validate.mutate(
      // A saved pack is checked under its own key, so its current name is not counted against it.
      { path: { org_id: orgId }, query: packKey ? { key: packKey } : undefined, body },
      {
        onSuccess: (check) => {
          setServer({
            json,
            issues: check.issues.map((i) => ({ step: i.step ?? undefined, path: i.path, message: i.message })),
          });
          if (check.ok) toast(t("checkOk"), t("checkOkBody"));
          else toast(t("checkFailed"), t("seeProblems"), "blocked");
        },
        onError: (e) => toast(t("checkError"), errorText(e), "blocked"),
      },
    );
  };

  // What the API could not read from an imported workflow.yaml, listed with the other problems and attached to
  // their steps. The steps are already on the canvas, so the draft they belong to is the one in the store now.
  const onImported = (issues: BuilderIssue[]) => {
    if (!issues.length) return;
    setServer({
      json: JSON.stringify(draftOf(api.getState())),
      issues: issues.map((i) => ({ step: i.step ?? undefined, path: i.path, message: i.message })),
      imported: true,
    });
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <div className="mr-auto min-w-0">
          <div className="truncate text-sm font-semibold">{details.name || t("untitled")}</div>
          <div className="text-xs text-muted">
            {base ? t("version", { n: base }) : t("notSavedYet")}
            {dirty ? ` · ${t("unsaved")}` : ""}
          </div>
        </div>
        {/* A member may read the saved workflow.yaml; only a builder may import one. */}
        <YamlDialog packKey={packKey} dirty={dirty} readOnly={locked} onImported={onImported} />
        {canBuild ? (
          <>
            <Button
              variant="ghost"
              className="px-2.5"
              onClick={() => api.getState().undo()}
              disabled={!canUndo || locked}
              aria-label={t("undo")}
              title={t("undo")}
            >
              <Undo2 className="size-4" aria-hidden />
            </Button>
            <Button
              variant="ghost"
              className="px-2.5"
              onClick={() => api.getState().redo()}
              disabled={!canRedo || locked}
              aria-label={t("redo")}
              title={t("redo")}
            >
              <Redo2 className="size-4" aria-hidden />
            </Button>
            <TestDialog
              packKey={packKey}
              dirty={dirty}
              inputFields={details.inputFields ?? []}
              budgetMinor={details.budgetMinor}
            />
            {packKey ? (
              <SubmitButton
                kind="pack"
                keyName={packKey}
                name={details.name}
                dirty={dirty}
                inputFields={details.inputFields ?? []}
              />
            ) : null}
            <Button variant="secondary" onClick={onValidate} disabled={validate.isPending || !orgId}>
              {t("validate")}
            </Button>
            {noChanges ? (
              <span id={saveHintId} className="text-xs text-muted">
                {t("noChanges")}
              </span>
            ) : null}
            <Button
              onClick={onSave}
              disabled={create.isPending || save.isPending || !orgId || noChanges}
              aria-describedby={noChanges ? saveHintId : undefined}
            >
              {t("save")}
            </Button>
          </>
        ) : (
          <p className="text-sm text-muted">{tStudio("buildersOnly")}</p>
        )}
      </div>

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

      {heldDetail ? (
        <Callout tone="blocked" title={t("runsInProgress")}>
          {t("runsInProgressBody")}
          <span className="mt-1 block text-muted">{heldDetail}</span>
        </Callout>
      ) : null}

      <StepIssuesContext.Provider value={counts}>
        <ReadOnlyContext.Provider value={locked}>
          <div className="grid gap-4 xl:grid-cols-[280px_minmax(0,1fr)_360px]">
            <Section className="flex max-h-[680px] flex-col overflow-hidden">
              <div className="border-b border-rule p-3">
                <Segmented
                  label={t("panels")}
                  value={panel}
                  onValueChange={setPanel}
                  options={[
                    { value: "steps", label: t("stepsPanel") },
                    { value: "add", label: t("addPanel") },
                  ]}
                />
              </div>
              <div className="min-h-0 flex-1 overflow-y-auto">
                {panel === "steps" ? <StepList disabled={locked} /> : <PalettePanel disabled={locked} />}
              </div>
              {withCanvas ? null : <p className="border-t border-rule p-3 text-xs text-muted">{t("smallScreen")}</p>}
            </Section>
            {withCanvas ? (
              <Section className="h-[680px] overflow-hidden">
                <EditorCanvas readOnly={locked} />
              </Section>
            ) : null}
            <Section
              title={selectedId ? t("stepSettings") : t("packDetails")}
              headingRef={panelHeading}
              aside={
                selectedId ? (
                  <Button variant="ghost" className="h-8" onClick={() => pickDetails()}>
                    {t("showDetails")}
                  </Button>
                ) : null
              }
              className="max-h-[680px] overflow-y-auto"
            >
              {/* One switch makes every native field inside read-only for a member; Base UI controls read the context. */}
              <fieldset disabled={locked} className="min-w-0">
                {selectedId ? (
                  <StepSettings afterRemove={() => panelHeading.current?.focus()} />
                ) : (
                  <DetailsForm issues={detailProblems} nameErrors={nameErrors} focus={focus} onFocused={focused} />
                )}
              </fieldset>
            </Section>
          </div>
        </ReadOnlyContext.Provider>
        <IssuesPanel local={local} server={current} checked={checked} onPick={pick} onPickDetails={pickDetails} />
      </StepIssuesContext.Provider>
    </div>
  );
}
