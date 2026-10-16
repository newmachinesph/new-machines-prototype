import type { ReactNode } from "react";

/**
 * A missing page inside an area's shell: the sidebar and top bar stay, so the person is still where they were,
 * and the actions lead on within that area. The bare page outside any shell is `app/not-found.tsx`.
 */
export function NotFoundPanel({ title, body, children }: { title: string; body: string; children: ReactNode }) {
  return (
    <div className="panel mx-auto max-w-xl px-6 py-10">
      <title>{`${title} | New Machines`}</title>
      <h1 className="h-page">{title}</h1>
      <p className="mt-3 text-[15px] leading-relaxed text-grey-700">{body}</p>
      <div className="mt-6 flex flex-wrap gap-2">{children}</div>
    </div>
  );
}
