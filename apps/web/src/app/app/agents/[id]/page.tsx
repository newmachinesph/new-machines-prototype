import { AgentPage } from "./agent-page";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <AgentPage id={id} />;
}
