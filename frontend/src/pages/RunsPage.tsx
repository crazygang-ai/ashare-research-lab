import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Play } from "lucide-react";
import { Link, useParams } from "react-router-dom";

import { executeUiRun, fetchUiRun, fetchUiRuns } from "../api/client";
import CommandPreview from "../components/CommandPreview";
import LogStream from "../components/LogStream";
import RunTimeline from "../components/RunTimeline";
import StatusBadge from "../components/StatusBadge";
import { useI18n } from "../i18n";

export default function RunsPage() {
  const { t } = useI18n();
  const { uiRunId } = useParams();
  const queryClient = useQueryClient();
  const runsQuery = useQuery({ queryKey: ["ui-runs"], queryFn: fetchUiRuns, refetchInterval: 5000 });
  const selectedId = uiRunId ?? runsQuery.data?.runs[0]?.ui_run_id;
  const selectedQuery = useQuery({
    queryKey: ["ui-run", selectedId],
    queryFn: () => fetchUiRun(selectedId as string),
    enabled: Boolean(selectedId),
    refetchInterval: 5000
  });
  const executeRun = useMutation({
    mutationFn: executeUiRun,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["ui-runs"] });
      void queryClient.invalidateQueries({ queryKey: ["ui-run", selectedId] });
    }
  });
  const selectedRun = selectedQuery.data?.run;

  return (
    <div className="grid gap-5 xl:grid-cols-[22rem_minmax(0,1fr)]">
      <aside className="rounded-md border border-ink-200 bg-white shadow-panel">
        <div className="border-b border-ink-200 px-4 py-3">
          <h2 className="text-lg font-semibold">{t("page.runs.title")}</h2>
        </div>
        <div className="max-h-[calc(100dvh-12rem)] overflow-auto p-2">
          {runsQuery.data?.runs.length ? (
            runsQuery.data.runs.map((run) => (
              <Link
                key={run.ui_run_id}
                to={`/runs/${run.ui_run_id}`}
                className={[
                  "block rounded-md p-3 hover:bg-ink-100",
                  run.ui_run_id === selectedId ? "bg-ink-100" : ""
                ].join(" ")}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium">{run.task_type}</span>
                  <StatusBadge status={run.status} />
                </div>
                <p className="mt-2 truncate font-mono text-xs text-ink-500">{run.ui_run_id}</p>
              </Link>
            ))
          ) : (
            <p className="p-3 text-sm text-ink-500">{t("page.runs.empty")}</p>
          )}
        </div>
      </aside>

      <div className="space-y-5">
        <section className="rounded-md border border-ink-200 bg-white p-4 shadow-panel">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h2 className="text-lg font-semibold">{selectedRun?.task_type ?? t("page.runs.detail")}</h2>
              <p className="mt-1 font-mono text-xs text-ink-500">{selectedRun?.ui_run_id ?? "-"}</p>
            </div>
            <button
              type="button"
              className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md bg-ink-900 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
              disabled={!selectedRun || selectedRun.status === "running" || executeRun.isPending}
              onClick={() => selectedRun && executeRun.mutate(selectedRun.ui_run_id)}
            >
              <Play className="h-4 w-4" aria-hidden="true" />
              {t("page.runs.execute")}
            </button>
          </div>
        </section>

        <div className="grid gap-5 xl:grid-cols-2">
          <section className="rounded-md border border-ink-200 bg-white p-4 shadow-panel">
            <h2 className="mb-3 text-base font-semibold">{t("page.runs.timeline")}</h2>
            <RunTimeline run={selectedRun} />
          </section>
          <CommandPreview command={selectedRun?.command_preview} />
        </div>

        <section className="rounded-md border border-ink-200 bg-white p-4 shadow-panel">
          <h2 className="mb-3 text-base font-semibold">{t("page.runs.logs")}</h2>
          <LogStream run={selectedRun} />
        </section>
      </div>
    </div>
  );
}
