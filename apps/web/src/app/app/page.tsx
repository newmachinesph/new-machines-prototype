import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { Overview } from "./overview";

export async function generateMetadata(): Promise<Metadata> {
  return { title: (await getTranslations("nav"))("overview") };
}

export default function OverviewPage() {
  return <Overview />;
}
