import type { Metadata } from "next";
import { Suspense } from "react";
import { DefinitionDetailView } from "../../_components/definition-detail";

export const metadata: Metadata = { title: "Definition" };

/** A malformed `%` sequence in the URL must not take the page down. */
function safeDecode(segment: string): string {
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment;
  }
}

/** A catch-all key, because a schema's key (`<pack>/<name>`) has a slash in it. */
export default async function DefinitionPage({ params }: { params: Promise<{ kind: string; key: string[] }> }) {
  const { kind, key } = await params;
  return (
    <Suspense>
      <DefinitionDetailView kind={safeDecode(kind)} defKey={key.map(safeDecode).join("/")} />
    </Suspense>
  );
}
