import { useEffect } from "react";
import type { LogRecord, TaskRecord } from "../../shared/types";

export function useTaskEvents(
  backendUrl: string,
  onTaskUpdate: (task: TaskRecord) => void,
  onLogUpdate: (log: LogRecord) => void,
  onBackendState: (online: boolean) => void
) {
  useEffect(() => {
    if (!backendUrl) {
      return;
    }

    const unsubscribe = window.cliplab.subscribeTaskEvents(
      `${backendUrl}/api/events`,
      (payload) => {
        try {
          const parsed = JSON.parse(payload) as { type: string; task?: TaskRecord; log?: LogRecord };
          if (parsed.type === "heartbeat") {
            onBackendState(true);
            return;
          }
          if (parsed.type === "task_update" && parsed.task) {
            onBackendState(true);
            onTaskUpdate(parsed.task);
            return;
          }
          if (parsed.type === "log_update" && parsed.log) {
            onBackendState(true);
            onLogUpdate(parsed.log);
          }
        } catch {
          onBackendState(false);
        }
      },
      () => {
        onBackendState(false);
      }
    );

    return () => unsubscribe();
  }, [backendUrl, onTaskUpdate, onLogUpdate, onBackendState]);
}
