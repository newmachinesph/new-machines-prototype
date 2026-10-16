import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { ListingView } from "./listing-view";

export async function generateMetadata(): Promise<Metadata> {
  return { title: (await getTranslations("nav"))("studioPublisher") };
}

export default async function StudioListingPage({ params }: { params: Promise<{ listingId: string }> }) {
  const { listingId } = await params;
  return <ListingView listingId={listingId} />;
}
