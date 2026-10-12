import { AppShell } from "@/components/shell";
import { Guard } from "@/lib/auth/guard";

export default function BusinessLayout({ children }: { children: React.ReactNode }) {
  return (
    <Guard>
      <AppShell mode="business">{children}</AppShell>
    </Guard>
  );
}
