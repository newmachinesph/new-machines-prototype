import type { Metadata } from "next";
import { PackDetail } from "../_components/pack-detail";

export const metadata: Metadata = { title: "Pack" };

export default async function PackPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  return <PackDetail slug={slug} />;
}
