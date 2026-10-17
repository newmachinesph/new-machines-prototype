"use client";

import { Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { parseAsString, useQueryState } from "nuqs";
import { useEffect, useId, useRef, useState } from "react";
import { focusAfterClose, Segmented, useToast } from "@/components/base";
import { ConfirmAction } from "@/components/confirm-action";
import { type Column, DataTable } from "@/components/data-table";
import { QueryState } from "@/components/query-state";
import { ReadOnly } from "@/components/read-only";
import { isRuntimeOff, RuntimeOff } from "@/components/runtime-off";
import { Skeleton } from "@/components/skeleton";
import { Button, PageHeader, Pill, Section } from "@/components/ui";
import type { MemorySpace, MemorySpaceItem } from "@/lib/api/gen/types.gen";
import { dateTime } from "@/lib/format";
import { useAddMemoryItem, useDeleteMemoryItem, useMemoryItems, useMemorySpaces } from "@/lib/queries/memory";
import { useCanWrite } from "@/lib/queries/ops";
import { definitionHref } from "../../definitions/_components/definition-logic";

/** The API's bounds for an item's text, after trimming. */
export const ITEM_MAX = 2000;

const SOURCE: Record<string, string> = { seed: "Seed", console: "Console", agent: "Agent", team: "Team" };
const sourceLabel = (s: string) => SOURCE[s] ?? s.charAt(0).toUpperCase() + s.slice(1);
const short = (text: string, n = 60) => (text.length > n ? `${text.slice(0, n - 1)}…` : text);

export function MemoryView() {
  const spaces = useMemorySpaces();
  const [space, setSpace] = useQueryState("space", parseAsString);
  const known = spaces.data;
  // A space in the URL that does not exist (renamed, mistyped) falls back to the first one.
  useEffect(() => {
    if (known && space && !known.some((s) => s.key === space)) void setSpace(null);
  }, [known, space, setSpace]);

  const current = known?.find((s) => s.key === space) ?? known?.[0] ?? null;

  return (
    <>
      <PageHeader
        title="Memory"
        lede="What agents know before they start, by memory space. Add or delete items with a reason; agents see the change from their next run."
        actions={current ? <AddItem space={current} /> : null}
      />
      {isRuntimeOff(spaces.error) ? (
        <RuntimeOff what="Memory spaces" />
      ) : (
        <QueryState query={spaces} skeleton={<Skeleton className="h-96" />}>
          {(list) =>
            current ? (
              <div className="space-y-4">
                <div className="max-w-full overflow-x-auto">
                  <Segmented
                    label="Memory space"
                    value={current.key}
                    onValueChange={(k) => void setSpace(k)}
                    options={list.map((s) => ({ value: s.key, label: s.name, count: s.itemCount }))}
                  />
                </div>
                <SpaceItems space={current} />
              </div>
            ) : (
              <Section className="p-6">
                <p className="text-sm text-muted">No memory spaces yet. Create one from Definitions.</p>
              </Section>
            )
          }
        </QueryState>
      )}
    </>
  );
}

function SpaceItems({ space }: { space: MemorySpace }) {
  const items = useMemoryItems(space.key);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const focusHeading = () => focusAfterClose(() => headingRef.current);

  const columns: Column<MemorySpaceItem>[] = [
    { key: "text", header: "Item", cell: (i) => <span className="block max-w-[70ch]">{i.text}</span> },
    {
      key: "source",
      header: "Source",
      className: "hidden sm:table-cell",
      cell: (i) => <Pill>{sourceLabel(i.source)}</Pill>,
    },
    {
      key: "by",
      header: "Added by",
      className: "hidden lg:table-cell",
      cell: (i) => <span className="break-all">{i.createdBy}</span>,
    },
    {
      key: "at",
      header: "Added",
      numeric: true,
      className: "hidden whitespace-nowrap md:table-cell",
      cell: (i) => dateTime(i.createdAt),
    },
    {
      key: "actions",
      header: <span className="sr-only">Actions</span>,
      cell: (i) => <DeleteItem item={i} onDone={focusHeading} />,
    },
  ];

  return (
    <Section
      title={space.name}
      headingRef={headingRef}
      aside={
        <Link
          href={definitionHref("memory_space", space.key)}
          className="shrink-0 font-mono text-[12px] text-grey-700 underline-offset-2 hover:underline"
        >
          memory_space/{space.key} v{space.version}
        </Link>
      }
    >
      <p className="border-b border-rule px-5 py-3 text-sm text-grey-700">{space.description}</p>
      <QueryState query={items} skeleton={<Skeleton className="m-5 h-40" />}>
        {(rows) => (
          <DataTable
            label={`Items in ${space.name}`}
            columns={columns}
            rows={rows}
            rowKey={(i) => i.id}
            empty="No items in this space yet. Add one with Add item."
          />
        )}
      </QueryState>
    </Section>
  );
}

function AddItem({ space }: { space: MemorySpace }) {
  const id = useId();
  const canWrite = useCanWrite();
  const add = useAddMemoryItem();
  const toast = useToast();
  const [text, setText] = useState("");
  const trimmed = text.trim();
  const tooLong = trimmed.length > ITEM_MAX;

  const label = (
    <>
      <Plus className="size-4" aria-hidden />
      Add item
    </>
  );
  if (!canWrite) {
    return (
      <ReadOnly>
        <Button disabled>{label}</Button>
      </ReadOnly>
    );
  }
  return (
    <ConfirmAction
      trigger={<Button>{label}</Button>}
      title={`Add an item to ${space.name}?`}
      consequence="Agents that read this space see it from their next run. Runs already going keep what they recalled."
      confirmLabel="Add item"
      confirmDisabled={!trimmed || tooLong}
      reasonPlaceholder="Policy confirmed with the finance team"
      onOpenChange={(open) => {
        if (!open) setText("");
      }}
      onConfirm={async (reason) => {
        await add.mutateAsync({ path: { space: space.key }, body: { text: trimmed, reason } });
        toast("Memory item added", space.name);
      }}
    >
      <div className="text-sm">
        <label htmlFor={`${id}-text`} className="font-medium">
          Item
        </label>
        <textarea
          id={`${id}-text`}
          rows={4}
          value={text}
          onChange={(e) => setText(e.target.value)}
          aria-invalid={tooLong || undefined}
          aria-describedby={`${id}-count`}
          placeholder="Orders over $500 need a person to confirm the match."
          className="mt-1.5 block w-full resize-y rounded-md border border-grey-300 bg-paper px-3 py-2 text-sm outline-none focus:border-ink aria-[invalid]:border-blocked"
        />
        <p id={`${id}-count`} className={tooLong ? "mt-1 text-xs text-blocked" : "mt-1 text-xs text-muted"}>
          <span className="tnum">{trimmed.length}</span> of {ITEM_MAX.toLocaleString("en-US")} characters. One fact per
          item.
        </p>
      </div>
    </ConfirmAction>
  );
}

function DeleteItem({ item, onDone }: { item: MemorySpaceItem; onDone: () => void }) {
  const canWrite = useCanWrite();
  const remove = useDeleteMemoryItem();
  const toast = useToast();
  const button = (
    <Button variant="ghost" aria-label={`Delete: ${short(item.text)}`} className="px-2.5" disabled={!canWrite}>
      <Trash2 className="size-4" aria-hidden />
    </Button>
  );
  if (!canWrite) return <ReadOnly>{button}</ReadOnly>;
  return (
    <ConfirmAction
      trigger={button}
      title="Delete this memory item?"
      consequence={
        <>&ldquo;{short(item.text, 140)}&rdquo; is removed from the space. Agents stop seeing it from their next run.</>
      }
      confirmLabel="Delete item"
      destructive
      reasonPlaceholder="No longer true after the pricing change"
      onConfirm={async (reason) => {
        await remove.mutateAsync({ path: { item_id: item.id }, body: { reason } });
        toast("Memory item deleted");
        // The row and its button are gone, so focus lands on the space's heading.
        onDone();
      }}
    />
  );
}
