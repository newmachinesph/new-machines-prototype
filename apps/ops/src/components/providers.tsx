"use client";

import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ReactQueryDevtools } from "@tanstack/react-query-devtools";
import { NuqsAdapter } from "nuqs/adapters/next/app";
import { type ReactNode, useState } from "react";
import { handleUnauthorized } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { SessionProvider } from "@/lib/auth/session";

/** A rejected session signs out and returns to sign-in, whether a query or a mutation hit it. */
function redirectOnUnauthorized(e: unknown) {
  if (e instanceof ApiError && e.status === 401) void handleUnauthorized();
}

export function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        queryCache: new QueryCache({ onError: redirectOnUnauthorized }),
        mutationCache: new MutationCache({ onError: redirectOnUnauthorized }),
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            retry: (count, e) => !(e instanceof ApiError && e.status >= 400 && e.status < 500) && count < 2,
          },
        },
      }),
  );
  return (
    <QueryClientProvider client={queryClient}>
      <SessionProvider>
        <NuqsAdapter>{children}</NuqsAdapter>
      </SessionProvider>
      {process.env.NODE_ENV === "development" ? <ReactQueryDevtools buttonPosition="bottom-right" /> : null}
    </QueryClientProvider>
  );
}
