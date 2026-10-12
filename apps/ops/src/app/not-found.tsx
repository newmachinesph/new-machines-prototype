import { ButtonLink } from "@/components/ui";
import { Lockup } from "@/design-system/logo/Lockup";

export default function NotFound() {
  return (
    <main id="main" className="mx-auto flex min-h-dvh max-w-xl flex-col justify-center px-6">
      <Lockup trim className="h-8 w-auto text-ink" />
      <h1 className="mt-10 text-3xl font-semibold tracking-tight">There is nothing at this address</h1>
      <p className="mt-3 text-[15px] leading-relaxed text-grey-700">
        The tenant, pack or record may have a different ID, or the link is incomplete.
      </p>
      <div className="mt-6 flex flex-wrap gap-2">
        <ButtonLink href="/command">Go to command center</ButtonLink>
        <ButtonLink href="/tenants" variant="secondary">
          See all tenants
        </ButtonLink>
      </div>
    </main>
  );
}
