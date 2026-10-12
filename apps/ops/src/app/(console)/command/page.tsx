import type { Metadata } from "next";
import { CommandView } from "./_components/command-view";

export const metadata: Metadata = { title: "Command center" };

export default function CommandPage() {
  return <CommandView />;
}
