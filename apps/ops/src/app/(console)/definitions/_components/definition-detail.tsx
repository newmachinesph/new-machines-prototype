"use client";

import { ArrowLeft, Download } from "lucide-react";
import Link from "next/link";
import { parseAsInteger, parseAsString, useQueryState } from "nuqs";
import { type ReactNode, useState } from "react";
import { useToast } from "@/components/base";
import { QueryState } from "@/components/query-state";
import { READ_ONLY_TEXT } from "@/components/read-only";
import { isRuntimeOff, RuntimeOff } from "@/components/runtime-off";
import { Skeleton } from "@/components/skeleton";
import { Button, ButtonLink, Callout, Id, PageHeader, Pill, Section } from "@/components/ui";
import { ApiError } from "@/lib/api/errors";
import { errorText } from "@/lib/api/error-text";
import type { DefinitionDetail, DefinitionRef } from "@/lib/api/gen/types.gen";
import { cn } from "@/lib/cn";
import { downloadText } from "@/lib/download";
import { dateTime } from "@/lib/format";
import { type DefinitionKind, useDefinition, useFetchExport } from "@/lib/queries/definitions";
import { useCanWrite } from "@/lib/queries/ops";
import { DefinitionEditor } from "./definition-editor";
import { definitionHref, exportFileName, isKind, KIND_LABEL, templateFrom } from "./definition-logic";

const lower = (kind: DefinitionKind) => KIND_LABEL[kind].toLowerCase();

/** One definition: its text in the editor, its versions, what it refers to and what uses it. */
export function DefinitionDetailView({ kind, defKey }: { kind: string; defKey: string }) {
  if (!isKind(kind)) {
    return (
      <Missing title={`No definition kind ${kind}`}>
        Definitions are packs, workflows, contracts, agents, connectors, decision rules, memory spaces, schemas, model
        profiles and the taxonomy. Pick one from the list.
      </Missing>
    );
  }
  return <KnownKind kind={kind} defKey={defKey} />;
}

function KnownKind({ kind, defKey }: { kind: DefinitionKind; defKey: string }) {
  const [version, setVersion] = useQueryState("version", parseAsInteger);
  const [from, setFrom] = useQueryState("from", parseAsString);
  const query = useDefinition(kind, defKey, version);
  const notFound = query.error instanceof ApiError && query.error.status === 404;

  if (isRuntimeOff(query.error)) {
    return (
      <>
        <PageHeader title={`${KIND_LABEL[kind]} ${defKey}`}>
          <BackLink />
        </PageHeader>
        <RuntimeOff what="Definitions" />
      </>
    );
  }
  if (notFound && from && !version) {
    return <NewDefinition kind={kind} defKey={defKey} from={from} onCreated={() => void setFrom(null)} />;
  }
  if (notFound) {
    return (
      <Missing title={version ? `${kind}/${defKey} has no version ${version}` : `No ${lower(kind)} called ${defKey}`}>
        It may never have been published. Go back to the definitions list and pick it from there, or create it with New
        definition.
      </Missing>
    );
  }
  return (
    <QueryState query={query} skeleton={<Skeleton className="h-96" />}>
      {(detail) => (
        <DefinitionBody
          kind={kind}
          defKey={defKey}
          detail={detail}
          version={version}
          onPublished={() => void setVersion(null)}
        />
      )}
    </QueryState>
  );
}

function BackLink() {
  return (
    <Link href="/definitions" className="mb-3 inline-flex items-center gap-1.5 text-sm text-muted hover:text-ink">
      <ArrowLeft className="size-4" aria-hidden />
      Definitions
    </Link>
  );
}

function Missing({ title, children }: { title: string; children: ReactNode }) {
  return (
    <>
      <BackLink />
      <Section className="p-6">
        <h1 tabIndex={-1} className="h-page outline-none">
          {title}
        </h1>
        <p className="mt-2 max-w-[60ch] text-sm text-muted">{children}</p>
      </Section>
    </>
  );
}

function DefinitionBody({
  kind,
  defKey,
  detail,
  version,
  onPublished,
}: {
  kind: DefinitionKind;
  defKey: string;
  detail: DefinitionDetail;
  version: number | null;
  onPublished: () => void;
}) {
  const shown = detail.summary.version;
  const latest = detail.versions[0]?.version ?? shown;

  return (
    <>
      <PageHeader
        title={
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
            {detail.summary.name}
            <Pill>{KIND_LABEL[kind]}</Pill>
          </span>
        }
        lede={
          <>
            <Id>
              {kind}/{defKey}
            </Id>{" "}
            · v{shown} · {detail.summary.source === "console" ? "published from the console" : "applied from files"}
          </>
        }
        actions={<ExportButton kind={kind} defKey={defKey} version={version} />}
      >
        <BackLink />
      </PageHeader>

      {shown !== latest ? (
        <div className="mb-4">
          <Callout
            tone="info"
            title={`Viewing v${shown} of ${latest}`}
            action={
              <ButtonLink href={definitionHref(kind, defKey)} variant="secondary">
                Go to v{latest}
              </ButtonLink>
            }
          >
            Publishing from here makes this text the latest version, v{latest + 1}.
          </Callout>
        </div>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <Section title="Edit as text">
          <DefinitionEditor
            // Not keyed by the shown digest: a version published meanwhile must not wipe unpublished edits.
            key={version ?? "latest"}
            kind={kind}
            defKey={defKey}
            name={detail.summary.name}
            initial={{ yaml: detail.yaml, files: detail.files }}
            nextVersion={latest + 1}
            onPublished={onPublished}
          />
        </Section>
        <div className="space-y-4">
          <Section title="Versions">
            <ol aria-label="Versions" className="divide-y divide-rule">
              {detail.versions.map((v) => (
                <li key={v.version} className="px-5 py-3 text-sm">
                  <div className="flex items-baseline justify-between gap-3">
                    <Link
                      href={definitionHref(kind, defKey, v.version === latest ? null : v.version)}
                      aria-current={v.version === shown ? "page" : undefined}
                      className={cn(
                        "font-medium underline-offset-2 hover:underline",
                        v.version === shown && "underline",
                      )}
                    >
                      v{v.version}
                    </Link>
                    <time dateTime={v.publishedAt} className="tnum shrink-0 text-xs text-muted">
                      {dateTime(v.publishedAt)}
                    </time>
                  </div>
                  <div className="text-xs break-all text-muted">
                    {v.source === "console" ? "Console" : "File"} · {v.publishedBy}
                  </div>
                  {v.reason ? <p className="mt-1 text-grey-700">{v.reason}</p> : null}
                </li>
              ))}
            </ol>
          </Section>
          <RefSection title="Refers to" refs={detail.refs} empty="Refers to no other definition." />
          <RefSection title="Used by" refs={detail.usedBy} empty="No other definition uses it." />
        </div>
      </div>
    </>
  );
}

function RefSection({ title, refs, empty }: { title: string; refs: DefinitionRef[]; empty: string }) {
  return (
    <Section title={title}>
      {refs.length ? (
        <ul className="space-y-1.5 px-5 py-3 text-sm">
          {refs.map((r) => (
            <li key={`${r.kind}/${r.key}`}>
              <Link
                href={definitionHref(r.kind, r.key)}
                className="font-mono text-[12px] underline-offset-2 hover:underline"
              >
                {r.kind}/{r.key}
              </Link>
            </li>
          ))}
        </ul>
      ) : (
        <p className="px-5 py-3 text-sm text-muted">{empty}</p>
      )}
    </Section>
  );
}

/** Gap between downloads: browsers drop or block several downloads started in the same instant. */
const DOWNLOAD_GAP_MS = 250;
const pause = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/** Downloads every file of the version shown, one download per file, named by its path in the definitions folder. */
function ExportButton({ kind, defKey, version }: { kind: DefinitionKind; defKey: string; version: number | null }) {
  const fetchExport = useFetchExport();
  const toast = useToast();
  const [busy, setBusy] = useState(false);

  const run = async () => {
    setBusy(true);
    try {
      const { files } = await fetchExport(kind, defKey, version);
      const entries = Object.entries(files);
      for (const [i, [path, text]] of entries.entries()) {
        if (i > 0) await pause(DOWNLOAD_GAP_MS);
        downloadText(exportFileName(path), text);
      }
      // The browser decides whether each download goes through, so this only says what was started.
      toast(
        entries.length === 1 ? "Started 1 download" : `Started ${entries.length} downloads`,
        entries.length === 1
          ? "The name keeps its folder path."
          : "Allow multiple downloads if your browser asks. Each name keeps its folder path.",
      );
    } catch (e) {
      toast("Export failed", errorText(e), "blocked");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Button variant="secondary" onClick={() => void run()} disabled={busy} aria-busy={busy || undefined}>
      <Download className="size-4" aria-hidden />
      Export files
    </Button>
  );
}

/** A definition that does not exist yet, started from a copy of `from` with the key swapped. */
function NewDefinition({
  kind,
  defKey,
  from,
  onCreated,
}: {
  kind: DefinitionKind;
  defKey: string;
  from: string;
  onCreated: () => void;
}) {
  const canWrite = useCanWrite();
  const template = useDefinition(kind, from);
  const templateMissing = template.error instanceof ApiError && template.error.status === 404;

  const header = (
    <PageHeader
      title={`New ${lower(kind)}: ${defKey}`}
      lede={`A copy of ${from} with its key swapped. Edit it, validate it, then create version 1.`}
    >
      <BackLink />
    </PageHeader>
  );

  if (!canWrite) {
    return (
      <>
        {header}
        <Section className="p-6">
          <p className="text-sm text-muted">{READ_ONLY_TEXT}. An owner or admin can create definitions.</p>
        </Section>
      </>
    );
  }
  if (isRuntimeOff(template.error)) {
    return (
      <>
        {header}
        <RuntimeOff what="Definitions" />
      </>
    );
  }
  if (templateMissing) {
    return (
      <>
        {header}
        <Section className="p-6">
          <p className="text-sm text-muted">
            There is no {lower(kind)} called {from} to copy. Start again from New definition.
          </p>
        </Section>
      </>
    );
  }
  return (
    <>
      {header}
      <QueryState query={template} skeleton={<Skeleton className="h-96" />}>
        {(t) => (
          <Section title="Edit as text">
            <DefinitionEditor
              kind={kind}
              defKey={defKey}
              name={defKey}
              initial={{ yaml: templateFrom(t.yaml, from, defKey, t.body.name), files: t.files }}
              nextVersion={1}
              isNew
              onPublished={onCreated}
            />
          </Section>
        )}
      </QueryState>
    </>
  );
}
