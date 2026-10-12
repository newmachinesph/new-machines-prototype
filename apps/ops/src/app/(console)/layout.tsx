import { OpsShell } from "@/components/ops-shell";
import { Guard } from "@/lib/auth/guard";

export default function ConsoleLayout({ children }: { children: React.ReactNode }) {
  return (
    <Guard>
      <OpsShell>{children}</OpsShell>
    </Guard>
  );
}
