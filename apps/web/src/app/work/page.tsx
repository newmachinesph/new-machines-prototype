import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { WorkView } from "./work-view";

export async function generateMetadata(): Promise<Metadata> {
  return { title: (await getTranslations("nav"))("availableTasks") };
}

export default function WorkPage() {
  return <WorkView />;
}
