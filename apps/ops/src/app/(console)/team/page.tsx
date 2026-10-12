import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { TeamView } from "./_components/team-view";

export const metadata: Metadata = { title: "Ops team" };

export default function TeamPage() {
  return (
    <>
      <PageHeader title="Ops team" lede="Staff with access to this console, their role and whether MFA is on." />
      <TeamView />
    </>
  );
}
