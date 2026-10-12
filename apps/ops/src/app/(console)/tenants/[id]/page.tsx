import type { Metadata } from "next";
import { TenantDetailView } from "../_components/tenant-detail";

export const metadata: Metadata = { title: "Tenant" };

export default async function TenantDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <TenantDetailView id={id} />;
}
