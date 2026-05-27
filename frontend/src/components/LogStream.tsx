import { useEffect, useState } from "react";

import { openLogStream, type LogEvent } from "../api/logStream";
import type { UiRunRecord } from "../api/client";

export default function LogStream({ run }: { run?: UiRunRecord }) {
  const [events, setEvents] = useState<LogEvent[]>([]);

  useEffect(() => {
    setEvents([]);
    if (!run?.log_paths.length) {
      return undefined;
    }
    return openLogStream(run.ui_run_id, (event) => {
      setEvents((current) => [...current, event].slice(-500));
    });
  }, [run?.ui_run_id, run?.log_paths.length]);

  if (!run?.log_paths.length) {
    return <p className="rounded-md border border-dashed border-ink-300 bg-white p-4 text-sm text-ink-500">No log file recorded.</p>;
  }

  return (
    <pre className="max-h-96 overflow-auto rounded-md bg-ink-900 p-4 font-mono text-xs leading-5 text-ink-50">
      {events.map((event, index) =>
        event.type === "log" ? `${event.message}\n` : `[${event.type}] ${JSON.stringify(event)}\n`
      )}
      {!events.length ? "Waiting for log events...\n" : null}
    </pre>
  );
}
