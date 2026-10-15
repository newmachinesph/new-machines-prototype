import { AppShell } from "@/components/shell";
import { Guard } from "@/lib/auth/guard";
import { LiveOnly } from "./live-only";

export default function StudioLayout({ children }: { children: React.ReactNode }) {
  return (
    <Guard>
      <AppShell mode="studio">
        <LiveOnly>{children}</LiveOnly>
      </AppShell>
    </Guard>
  );
}
