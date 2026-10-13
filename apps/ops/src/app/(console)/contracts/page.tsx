import type { Metadata } from "next";
import { ContractsView } from "./_components/contracts-view";

export const metadata: Metadata = { title: "Work Contracts" };

export default function ContractsPage() {
  return <ContractsView />;
}
