import { ManagersOnly } from "./managers-only";

export default function PublisherLayout({ children }: { children: React.ReactNode }) {
  return <ManagersOnly>{children}</ManagersOnly>;
}
