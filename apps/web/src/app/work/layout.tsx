import { AppShell } from "@/components/shell";
import { Guard } from "@/lib/auth/guard";

export default function WorkLayout({ children }: { children: React.ReactNode }) {
  return (
    <Guard>
      <AppShell mode="work">{children}</AppShell>
    </Guard>
  );
}
