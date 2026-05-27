import type { UiRunStatus } from "./client";

export type LogEvent =
  | { type: "log"; message: string }
  | { type: "status"; status: UiRunStatus }
  | { type: string; [key: string]: unknown };

export function openLogStream(uiRunId: string, onEvent: (event: LogEvent) => void) {
  const source = new EventSource(`/api/v1/ui/runs/${encodeURIComponent(uiRunId)}/logs/stream`);
  source.onmessage = (message) => {
    try {
      onEvent(JSON.parse(message.data) as LogEvent);
    } catch {
      onEvent({ type: "log", message: message.data });
    }
  };
  return () => source.close();
}
