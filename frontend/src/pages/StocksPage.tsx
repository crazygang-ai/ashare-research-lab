import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FilePlus2, Search } from "lucide-react";
import { FormEvent, useState } from "react";

import {
  createStockReportRun,
  fetchStockFactors,
  fetchUiConfig,
  type StockReportRequest
} from "../api/client";
import CommandPreview from "../components/CommandPreview";
import DataTable from "../components/DataTable";
import StatusBadge from "../components/StatusBadge";

export default function StocksPage() {
  const queryClient = useQueryClient();
  const configQuery = useQuery({ queryKey: ["ui-config"], queryFn: fetchUiConfig });
  const [lookup, setLookup] = useState({
    stock_code: "002594.SZ",
    as_of: "2026-05-22",
    source_run_id: "hs300-factor-20260522"
  });
  const [submittedLookup, setSubmittedLookup] = useState(lookup);
  const [report, setReport] = useState<StockReportRequest>({
    stock_code: "002594.SZ",
    as_of: "2026-05-22",
    source_run_id: "hs300-factor-20260522",
    score_run_id: "hs300-score-20260522",
    scan_run_id: "hs300-scan-20260522",
    db_path: "data/processed/hs300_daily.duckdb",
    output_dir: "data/reports/generated/ui/stock",
    run_id: "ui-stock-report-20260522",
    confirmed: false
  });

  const factorsQuery = useQuery({
    queryKey: ["stock-factors", submittedLookup],
    queryFn: () =>
      fetchStockFactors(submittedLookup.stock_code, submittedLookup.as_of, submittedLookup.source_run_id),
    enabled: Boolean(submittedLookup.stock_code && submittedLookup.as_of && submittedLookup.source_run_id)
  });

  const createRun = useMutation({
    mutationFn: createStockReportRun,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["ui-runs"] })
  });

  function submitLookup(event: FormEvent) {
    event.preventDefault();
    setSubmittedLookup(lookup);
  }

  function submitReport(event: FormEvent) {
    event.preventDefault();
    createRun.mutate(report);
  }

  const runnerEnabled = configQuery.data?.ui_runner.enabled ?? false;

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_28rem]">
      <div className="space-y-5">
        <section className="rounded-md border border-ink-200 bg-white p-4 shadow-panel">
          <h2 className="text-lg font-semibold">Stocks</h2>
          <form onSubmit={submitLookup} className="mt-4 grid gap-3 md:grid-cols-[1fr_1fr_1fr_auto]">
            <label className="block text-sm font-medium">
              Stock Code
              <input
                className="mt-1 min-h-11 w-full rounded-md border border-ink-300 px-3 font-mono"
                value={lookup.stock_code}
                onChange={(event) => setLookup((current) => ({ ...current, stock_code: event.target.value }))}
                required
                pattern="\d{6}\.(SH|SZ)"
              />
            </label>
            <label className="block text-sm font-medium">
              As Of
              <input
                type="date"
                className="mt-1 min-h-11 w-full rounded-md border border-ink-300 px-3"
                value={lookup.as_of}
                onChange={(event) => setLookup((current) => ({ ...current, as_of: event.target.value }))}
                required
              />
            </label>
            <label className="block text-sm font-medium">
              Source Run ID
              <input
                className="mt-1 min-h-11 w-full rounded-md border border-ink-300 px-3 font-mono"
                value={lookup.source_run_id}
                onChange={(event) => setLookup((current) => ({ ...current, source_run_id: event.target.value }))}
                required
              />
            </label>
            <button
              type="submit"
              className="mt-6 inline-flex min-h-11 items-center justify-center gap-2 rounded-md bg-ink-900 px-4 py-2 text-sm font-semibold text-white"
            >
              <Search className="h-4 w-4" aria-hidden="true" />
              Lookup
            </button>
          </form>
        </section>
        <section className="space-y-3">
          <h2 className="text-base font-semibold">Factor Values</h2>
          <DataTable rows={factorsQuery.data?.rows} maxRows={40} />
        </section>
      </div>

      <aside className="space-y-4">
        <form onSubmit={submitReport} className="rounded-md border border-ink-200 bg-white p-4 shadow-panel">
          <div className="mb-4 flex items-center justify-between gap-3">
            <h2 className="text-base font-semibold">Stock Report Run</h2>
            <StatusBadge status={runnerEnabled ? "runner enabled" : "runner disabled"} />
          </div>
          <fieldset className="space-y-3" disabled={!runnerEnabled || createRun.isPending}>
            {Object.entries(report).map(([key, value]) => {
              if (key === "confirmed") {
                return (
                  <label key={key} className="flex min-h-11 items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={Boolean(value)}
                      onChange={(event) =>
                        setReport((current) => ({ ...current, confirmed: event.target.checked }))
                      }
                      required
                    />
                    confirmed
                  </label>
                );
              }
              return (
                <label key={key} className="block text-sm font-medium">
                  {key}
                  <input
                    type={key === "as_of" ? "date" : "text"}
                    className="mt-1 min-h-11 w-full rounded-md border border-ink-300 px-3 font-mono"
                    value={String(value ?? "")}
                    onChange={(event) =>
                      setReport((current) => ({
                        ...current,
                        [key]: event.target.value
                      }))
                    }
                    required={!["scan_run_id"].includes(key)}
                  />
                </label>
              );
            })}
            <button
              type="submit"
              className="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-md bg-ink-900 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
            >
              <FilePlus2 className="h-4 w-4" aria-hidden="true" />
              Create Report Run
            </button>
          </fieldset>
          {createRun.error ? <p className="mt-3 text-sm text-signal-red">{createRun.error.message}</p> : null}
        </form>
        {createRun.data?.run ? <CommandPreview command={createRun.data.run.command_preview} /> : null}
      </aside>
    </div>
  );
}
