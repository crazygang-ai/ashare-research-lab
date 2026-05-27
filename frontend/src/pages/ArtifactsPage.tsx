import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { fetchArtifacts } from "../api/client";
import ArtifactTable from "../components/ArtifactTable";
import { useI18n } from "../i18n";

const kinds = [
  "",
  "scan",
  "scoring",
  "backtest",
  "daily_report",
  "stock_report",
  "factor_validation"
];

export default function ArtifactsPage() {
  const { t } = useI18n();
  const [kind, setKind] = useState("");
  const artifactsQuery = useQuery({
    queryKey: ["artifacts", kind],
    queryFn: () => fetchArtifacts(kind || undefined)
  });

  return (
    <div className="space-y-5">
      <section className="rounded-md border border-ink-200 bg-white p-4 shadow-panel">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <h2 className="text-lg font-semibold">{t("page.artifacts.title")}</h2>
          <label className="text-sm font-medium">
            {t("page.artifacts.kind")}
            <select
              className="ml-2 min-h-11 rounded-md border border-ink-300 px-3"
              value={kind}
              onChange={(event) => setKind(event.target.value)}
            >
              {kinds.map((item) => (
                <option key={item || "all"} value={item}>
                  {item || t("page.artifacts.all")}
                </option>
              ))}
            </select>
          </label>
        </div>
      </section>
      <ArtifactTable artifacts={artifactsQuery.data?.artifacts ?? []} />
    </div>
  );
}
