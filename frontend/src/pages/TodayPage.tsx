import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Play, RefreshCw } from "lucide-react";
import { FormEvent, useState } from "react";

import {
  createHs300DailyRun,
  executeUiRun,
  fetchLatestDailyReportMarkdown,
  fetchLatestScan,
  fetchLatestScoring,
  fetchUiConfig
} from "../api/client";
import CommandPreview from "../components/CommandPreview";
import DataTable from "../components/DataTable";
import ReportViewer from "../components/ReportViewer";
import StatusBadge from "../components/StatusBadge";

type Hs300DailyForm = {
  as_of: string;
  stock_code: string;
  cache_mode: "use" | "refresh" | "offline";
  max_symbols: string;
  watchlist_file: string;
  confirmed: boolean;
};

export default function TodayPage() {
  const queryClient = useQueryClient();
  const configQuery = useQuery({ queryKey: ["ui-config"], queryFn: fetchUiConfig });
  const scanQuery = useQuery({ queryKey: ["latest-scan"], queryFn: fetchLatestScan });
  const scoringQuery = useQuery({ queryKey: ["latest-scoring"], queryFn: fetchLatestScoring });
  const reportQuery = useQuery({
    queryKey: ["latest-daily-report-markdown"],
    queryFn: fetchLatestDailyReportMarkdown
  });
  const [form, setForm] = useState<Hs300DailyForm>({
    as_of: "2026-05-22",
    stock_code: "002594.SZ",
    cache_mode: "use" as const,
    max_symbols: "",
    watchlist_file: "",
    confirmed: false
  });
  const [createdRunId, setCreatedRunId] = useState<string | null>(null);

  const createRun = useMutation({
    mutationFn: createHs300DailyRun,
    onSuccess: (payload) => {
      setCreatedRunId(payload.run.ui_run_id);
      void queryClient.invalidateQueries({ queryKey: ["ui-runs"] });
    }
  });
  const executeRun = useMutation({
    mutationFn: executeUiRun,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["ui-runs"] })
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    createRun.mutate({
      as_of: form.as_of,
      stock_code: form.stock_code,
      cache_mode: form.cache_mode,
      max_symbols: form.max_symbols ? Number(form.max_symbols) : undefined,
      watchlist_file: form.watchlist_file || undefined,
      confirmed: form.confirmed
    });
  }

  const runnerEnabled = configQuery.data?.ui_runner.enabled ?? false;
  const createdRun = createRun.data?.run;

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_24rem]">
      <div className="space-y-5">
        <section className="rounded-md border border-ink-200 bg-white p-4 shadow-panel">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h2 className="text-lg font-semibold">Today</h2>
              <p className="mt-1 text-sm text-ink-500">Daily research review</p>
            </div>
            <div className="flex gap-2">
              <StatusBadge status={scanQuery.data?.artifact_id ? "scan available" : "scan missing"} />
              <StatusBadge status={scoringQuery.data?.artifact_id ? "score available" : "score missing"} />
            </div>
          </div>
        </section>

        <section className="space-y-3">
          <h2 className="text-base font-semibold">Scored Candidates</h2>
          <DataTable rows={scoringQuery.data?.rows} maxRows={12} />
        </section>

        <section className="space-y-3">
          <h2 className="text-base font-semibold">Candidate Scan</h2>
          <DataTable rows={scanQuery.data?.rows} maxRows={12} />
        </section>

        <ReportViewer
          title="Daily Report"
          markdown={reportQuery.data}
          isLoading={reportQuery.isLoading}
          error={reportQuery.error}
        />
      </div>

      <aside className="space-y-4">
        <form onSubmit={submit} className="rounded-md border border-ink-200 bg-white p-4 shadow-panel">
          <div className="mb-4 flex items-center justify-between gap-3">
            <h2 className="text-base font-semibold">HS300 Daily Run</h2>
            <StatusBadge status={runnerEnabled ? "runner enabled" : "runner disabled"} />
          </div>
          <fieldset className="space-y-3" disabled={!runnerEnabled || createRun.isPending}>
            <label className="block text-sm font-medium">
              As Of
              <input
                type="date"
                className="mt-1 min-h-11 w-full rounded-md border border-ink-300 px-3"
                value={form.as_of}
                onChange={(event) => setForm((current) => ({ ...current, as_of: event.target.value }))}
                required
              />
            </label>
            <label className="block text-sm font-medium">
              Stock Code
              <input
                className="mt-1 min-h-11 w-full rounded-md border border-ink-300 px-3 font-mono"
                value={form.stock_code}
                onChange={(event) => setForm((current) => ({ ...current, stock_code: event.target.value }))}
                required
                pattern="\d{6}\.(SH|SZ)"
              />
            </label>
            <label className="block text-sm font-medium">
              Cache Mode
              <select
                className="mt-1 min-h-11 w-full rounded-md border border-ink-300 px-3"
                value={form.cache_mode}
                onChange={(event) =>
                  setForm((current) => ({ ...current, cache_mode: event.target.value as "use" | "refresh" | "offline" }))
                }
              >
                <option value="use">use</option>
                <option value="refresh">refresh</option>
                <option value="offline">offline</option>
              </select>
            </label>
            <label className="block text-sm font-medium">
              Max Symbols
              <input
                type="number"
                min="1"
                className="mt-1 min-h-11 w-full rounded-md border border-ink-300 px-3"
                value={form.max_symbols}
                onChange={(event) => setForm((current) => ({ ...current, max_symbols: event.target.value }))}
              />
            </label>
            <label className="block text-sm font-medium">
              Watchlist File
              <input
                className="mt-1 min-h-11 w-full rounded-md border border-ink-300 px-3 font-mono"
                value={form.watchlist_file}
                onChange={(event) => setForm((current) => ({ ...current, watchlist_file: event.target.value }))}
              />
            </label>
            <label className="flex min-h-11 items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={form.confirmed}
                onChange={(event) => setForm((current) => ({ ...current, confirmed: event.target.checked }))}
                required
              />
              confirmed
            </label>
            <button
              type="submit"
              className="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-md bg-ink-900 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
            >
              <RefreshCw className="h-4 w-4" aria-hidden="true" />
              Create Run
            </button>
          </fieldset>
          {createRun.error ? <p className="mt-3 text-sm text-signal-red">{createRun.error.message}</p> : null}
        </form>

        {createdRun ? (
          <>
            <CommandPreview command={createdRun.command_preview} />
            <button
              type="button"
              className="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-md border border-ink-300 bg-white px-4 py-2 text-sm font-semibold hover:bg-ink-100 disabled:cursor-not-allowed disabled:opacity-50"
              disabled={!createdRunId || executeRun.isPending}
              onClick={() => createdRunId && executeRun.mutate(createdRunId)}
            >
              <Play className="h-4 w-4" aria-hidden="true" />
              Execute Run
            </button>
          </>
        ) : null}
      </aside>
    </div>
  );
}
