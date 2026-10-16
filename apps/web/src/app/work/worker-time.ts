"use client";

import { WORKER_TZ } from "@/lib/format";
import { useFormat } from "@/lib/use-format";

/** Date and time in the reviewer portal's zone, with the zone named the one way the interface names zones
 * ("Oct 11, 10:00 PM Manila time"). */
export function useWorkerDateTime() {
  const { dateTime } = useFormat();
  return (iso: string) => dateTime(iso, WORKER_TZ);
}
