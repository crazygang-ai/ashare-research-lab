import type { UiRunRecord } from "../api/client";
import StatusBadge from "./StatusBadge";

export default function RunTimeline({ run }: { run?: UiRunRecord }) {
  if (!run) {
    return <p className="text-sm text-ink-500">Select a run to inspect details.</p>;
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge status={run.status} />
        <span className="font-mono text-xs text-ink-500">{run.ui_run_id}</span>
      </div>
      <div className="space-y-2">
        {run.steps.length ? (
          run.steps.map((step, index) => (
            <div key={`${String(step.name)}-${index}`} className="rounded-md border border-ink-200 bg-white px-3 py-2">
              <div className="flex items-center justify-between gap-3">
                <span className="text-sm font-medium">{String(step.name ?? `step-${index + 1}`)}</span>
                <StatusBadge status={String(step.status ?? "unknown")} />
              </div>
              <p className="mt-1 font-mono text-xs text-ink-500">
                {String(step.started_at ?? "-")} / {String(step.finished_at ?? "-")}
              </p>
            </div>
          ))
        ) : (
          <div className="rounded-md border border-dashed border-ink-300 bg-white p-3 text-sm text-ink-500">No steps recorded.</div>
        )}
      </div>
      {run.error_message ? <p className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800">{run.error_message}</p> : null}
    </div>
  );
}
