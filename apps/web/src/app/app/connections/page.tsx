import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { Button, PageHeader } from "@/components/ui";
import { ConnectDialog, ConnectionList } from "./connection-list";

export async function generateMetadata(): Promise<Metadata> {
  return { title: (await getTranslations("nav"))("connections") };
}

export default async function ConnectionsPage() {
  const t = await getTranslations("connections");
  return (
    <>
      <PageHeader
        title={t("title")}
        lede={t("lede")}
        actions={<ConnectDialog trigger={<Button variant="secondary">{t("connect.title")}</Button>} />}
      />
      <ConnectionList />
    </>
  );
}
