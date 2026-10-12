import { InstallPage } from "./install-page";

export default async function Page({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  return <InstallPage slug={slug} />;
}
