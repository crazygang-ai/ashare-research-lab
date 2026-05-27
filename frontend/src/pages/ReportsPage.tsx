import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { fetchLatestDailyReportMarkdown, fetchLatestStockReportMarkdown } from "../api/client";
import ReportViewer from "../components/ReportViewer";

type ReportKind = "daily" | "stock";

export default function ReportsPage() {
  const [kind, setKind] = useState<ReportKind>("daily");
  const dailyQuery = useQuery({
    queryKey: ["latest-daily-report-markdown"],
    queryFn: fetchLatestDailyReportMarkdown
  });
  const stockQuery = useQuery({
    queryKey: ["latest-stock-report-markdown"],
    queryFn: fetchLatestStockReportMarkdown
  });
  const active = kind === "daily" ? dailyQuery : stockQuery;

  return (
    <div className="space-y-5">
      <section className="rounded-md border border-ink-200 bg-white p-4 shadow-panel">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <h2 className="text-lg font-semibold">Reports</h2>
          <div className="inline-flex rounded-md border border-ink-300 bg-ink-100 p-1">
            {(["daily", "stock"] as const).map((item) => (
              <button
                key={item}
                type="button"
                className={[
                  "min-h-10 rounded px-3 text-sm font-medium",
                  kind === item ? "bg-white text-ink-900 shadow-panel" : "text-ink-600 hover:text-ink-900"
                ].join(" ")}
                onClick={() => setKind(item)}
              >
                {item === "daily" ? "Daily" : "Stock"}
              </button>
            ))}
          </div>
        </div>
      </section>
      <ReportViewer
        title={kind === "daily" ? "Daily Report" : "Stock Report"}
        markdown={active.data}
        isLoading={active.isLoading}
        error={active.error}
      />
    </div>
  );
}
