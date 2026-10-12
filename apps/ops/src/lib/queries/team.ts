"use client";

import { useQuery } from "@tanstack/react-query";
import { opsListTeamOptions } from "@/lib/api/gen/@tanstack/react-query.gen";

export const useTeam = () => useQuery(opsListTeamOptions());
