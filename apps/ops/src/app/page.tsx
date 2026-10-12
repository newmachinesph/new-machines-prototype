import { Lockup } from "@/design-system/logo/Lockup";
import { SignInForm } from "./sign-in-form";

export default function SignInPage() {
  return (
    <div className="flex min-h-dvh flex-col bg-stage">
      <header className="flex items-center justify-between gap-4 bg-chrome px-5 py-4 sm:px-8">
        <Lockup trim className="h-7 w-auto text-paper" />
        <p className="text-right text-[13px] text-chrome-muted">Staff only</p>
      </header>
      <main id="main" className="flex flex-1 items-start justify-center px-4 py-12 sm:items-center sm:py-16">
        <div className="panel w-full max-w-[400px] p-6 sm:p-7">
          <h1 className="text-lg font-semibold tracking-tight">New Machines operator console</h1>
          <p className="mt-1 text-sm leading-relaxed text-muted">
            Sign in with your New Machines staff account to manage tenants, the catalog and the platform.
          </p>
          <SignInForm />
        </div>
      </main>
    </div>
  );
}
