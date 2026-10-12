"use client";

import { useQuery } from "@tanstack/react-query";
import { opsGetOverviewOptions } from "@/lib/api/gen/@tanstack/react-query.gen";

/** Command center data. Polled so the attention queue stays current while an operator keeps the page open. */
export const useOverview = () => useQuery({ ...opsGetOverviewOptions(), refetchInterval: 30_000 });
