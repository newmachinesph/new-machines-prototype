"use client";

import { useQuery } from "@tanstack/react-query";
import { opsGetBillingOptions } from "@/lib/api/gen/@tanstack/react-query.gen";

export const useBilling = () => useQuery(opsGetBillingOptions());
