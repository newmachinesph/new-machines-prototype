import type { Metadata } from "next";
import { ListingDetail } from "../_components/listing-detail";

export const metadata: Metadata = { title: "Listing" };

export default async function ListingPage({ params }: { params: Promise<{ listingId: string }> }) {
  const { listingId } = await params;
  return <ListingDetail listingId={listingId} />;
}
