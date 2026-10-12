"use client";

import { notFound } from "next/navigation";
import { QueryState } from "@/components/query-state";
import { Skeleton } from "@/components/skeleton";
import { ApiError } from "@/lib/api/errors";
import { useTask } from "@/lib/queries/tasks";
import { TaskWorkspace } from "./task-workspace";

export function TaskPage({ id }: { id: string }) {
  const task = useTask(id);
  if (task.error instanceof ApiError && task.error.status === 404) notFound();
  return (
    <QueryState query={task} skeleton={<TaskSkeleton />}>
      {(t) => (
        <>
          <title>{`${t.title} | New Machines`}</title>
          <TaskWorkspace task={t} buyer={t.buyer} />
        </>
      )}
    </QueryState>
  );
}

function TaskSkeleton() {
  return (
    <div className="space-y-6">
      <Skeleton className="h-16 w-2/3" />
      <Skeleton className="h-72" />
    </div>
  );
}
