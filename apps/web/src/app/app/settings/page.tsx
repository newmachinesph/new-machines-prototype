import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { PageHeader } from "@/components/ui";
import { MembersSection, TokensSection } from "./access";
import { PublisherSection } from "./publisher";
import { PoliciesSection, WorkspaceSection } from "./workspace";

export async function generateMetadata(): Promise<Metadata> {
  return { title: (await getTranslations("nav"))("settings") };
}

export default async function SettingsPage() {
  const t = await getTranslations("settings");
  // In-page links for the one-column layout, where the sections stack into a long page.
  const sections = [
    { id: "policies", label: t("policies.title") },
    { id: "members", label: t("members.title") },
    { id: "ai-tools", label: t("tokens.title") },
    { id: "workspace", label: t("workspace.title") },
  ];
  return (
    <>
      <PageHeader title={t("title")} lede={t("lede")} />
      <nav aria-label={t("onThisPage")} className="mb-5 xl:hidden">
        <ul className="flex flex-wrap gap-x-4 gap-y-2 text-sm">
          {sections.map((s) => (
            <li key={s.id}>
              <a href={`#${s.id}`} className="link inline-block py-1">
                {s.label}
              </a>
            </li>
          ))}
        </ul>
      </nav>
      <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-2">
        <div id="policies" className="scroll-mt-24 lg:scroll-mt-20">
          <PoliciesSection />
        </div>

        <div className="space-y-6">
          <div id="members" className="scroll-mt-24 lg:scroll-mt-20">
            <MembersSection />
          </div>
          <div id="ai-tools" className="scroll-mt-24 lg:scroll-mt-20">
            <TokensSection />
          </div>
          <div id="workspace" className="scroll-mt-24 lg:scroll-mt-20">
            <WorkspaceSection />
          </div>
          <div id="publishing" className="scroll-mt-24 lg:scroll-mt-20">
            <PublisherSection />
          </div>
        </div>
      </div>
    </>
  );
}
