import type { Metadata } from "next";
import { AgentsView } from "./_components/agents-view";

export const metadata: Metadata = { title: "Agents" };

export default function AgentsPage() {
  return <AgentsView />;
}
