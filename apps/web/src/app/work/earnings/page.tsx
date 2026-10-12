import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { EarningsView } from "./earnings-view";

export async function generateMetadata(): Promise<Metadata> {
  return { title: (await getTranslations("nav"))("earnings") };
}

export default function EarningsPage() {
  return <EarningsView />;
}
