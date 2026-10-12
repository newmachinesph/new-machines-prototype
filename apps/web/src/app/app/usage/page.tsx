import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { UsageView } from "./usage-view";

export async function generateMetadata(): Promise<Metadata> {
  return { title: (await getTranslations("nav"))("usage") };
}

export default function UsagePage() {
  return <UsageView />;
}
