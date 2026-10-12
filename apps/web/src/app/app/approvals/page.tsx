import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { ApprovalsView } from "./approvals-view";

export async function generateMetadata(): Promise<Metadata> {
  return { title: (await getTranslations("nav"))("approvals") };
}

export default function ApprovalsPage() {
  return <ApprovalsView />;
}
