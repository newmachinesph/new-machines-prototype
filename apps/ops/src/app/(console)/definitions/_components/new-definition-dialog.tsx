"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useId, useState } from "react";
import { Modal, Select } from "@/components/base";
import { Button } from "@/components/ui";
import type { DefinitionSummary } from "@/lib/api/gen/types.gen";
import { cn } from "@/lib/cn";
import type { DefinitionKind } from "@/lib/queries/definitions";
import { CREATABLE_KINDS, definitionHref, KIND_LABEL, keyProblem } from "./definition-logic";

const INPUT =
  "mt-1.5 block h-9 w-full rounded-md border border-grey-300 bg-paper px-3 font-mono text-sm outline-none focus:border-ink aria-[invalid]:border-blocked";

/**
 * Starts a new definition: pick a kind, a key and an existing definition of that kind to copy. The editor opens
 * with the copy (its key swapped); nothing is saved until it is published there with a reason.
 */
export function NewDefinitionDialog({
  open,
  onOpenChange,
  definitions,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  definitions: DefinitionSummary[];
}) {
  const id = useId();
  const router = useRouter();
  const keysOf = (kind: DefinitionKind) => definitions.filter((d) => d.kind === kind).map((d) => d.key);
  // A new definition starts from a copy, so only kinds with at least one definition are offered.
  const kinds = CREATABLE_KINDS.filter((k) => keysOf(k).length > 0);
  const [kind, setKind] = useState<DefinitionKind | undefined>(kinds[0]);
  const [from, setFrom] = useState<string | undefined>(kind ? keysOf(kind)[0] : undefined);
  const [key, setKey] = useState("");
  const [problem, setProblem] = useState<string | null>(null);

  const close = (next: boolean) => {
    onOpenChange(next);
    if (!next) {
      setKey("");
      setProblem(null);
    }
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!kind || !from) return;
    const trimmed = key.trim();
    const why =
      keyProblem(kind, trimmed) ??
      (keysOf(kind).includes(trimmed)
        ? `A ${KIND_LABEL[kind].toLowerCase()} called ${trimmed} already exists. Open it from the list to edit it.`
        : null);
    setProblem(why);
    if (why) return;
    router.push(`${definitionHref(kind, trimmed)}?from=${encodeURIComponent(from)}`);
  };

  return (
    <Modal
      open={open}
      onOpenChange={close}
      title="New definition"
      description="Starts from a copy of an existing definition of the same kind. Nothing is saved until you publish it."
    >
      {kind && from ? (
        <form onSubmit={submit} noValidate className="mt-4 space-y-4">
          <div className="text-sm">
            <label htmlFor={`${id}-kind`} className="font-medium">
              Kind
            </label>
            <Select
              id={`${id}-kind`}
              label="Kind"
              value={kind}
              onValueChange={(k) => {
                setKind(k);
                setFrom(keysOf(k)[0]);
                setProblem(null);
              }}
              items={kinds.map((k) => ({ value: k, label: KIND_LABEL[k] }))}
              className="mt-1.5 w-full"
            />
          </div>
          <div className="text-sm">
            <label htmlFor={`${id}-from`} className="font-medium">
              Copy from
            </label>
            <Select
              id={`${id}-from`}
              label="Copy from"
              value={from}
              onValueChange={setFrom}
              items={keysOf(kind).map((k) => ({ value: k, label: k }))}
              className="mt-1.5 w-full"
            />
          </div>
          <div className="text-sm">
            <label htmlFor={`${id}-key`} className="font-medium">
              Key
            </label>
            <input
              id={`${id}-key`}
              value={key}
              onChange={(e) => setKey(e.target.value)}
              placeholder={kind === "schema" ? "<pack>/<name>" : "returns-agent"}
              aria-invalid={problem ? true : undefined}
              aria-describedby={problem ? `${id}-error` : `${id}-hint`}
              className={cn(INPUT)}
            />
            {problem ? (
              <p id={`${id}-error`} role="alert" className="mt-1 text-xs text-blocked">
                {problem}
              </p>
            ) : (
              <p id={`${id}-hint`} className="mt-1 text-xs text-muted">
                Lowercase letters, numbers, hyphens or underscores. Other definitions refer to it by this key.
              </p>
            )}
          </div>
          <div className="flex flex-wrap justify-end gap-2">
            <Button variant="ghost" onClick={() => close(false)}>
              Cancel
            </Button>
            <Button type="submit">Open editor</Button>
          </div>
        </form>
      ) : (
        <p className="mt-4 text-sm text-muted">There is no definition to copy yet. Apply the definition files first.</p>
      )}
    </Modal>
  );
}
