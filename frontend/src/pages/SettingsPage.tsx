import { useQuery } from "@tanstack/react-query";

import { fetchUiConfig } from "../api/client";
import StatusBadge from "../components/StatusBadge";
import { useI18n } from "../i18n";

export default function SettingsPage() {
  const { t } = useI18n();
  const configQuery = useQuery({ queryKey: ["ui-config"], queryFn: fetchUiConfig });
  const config = configQuery.data;

  return (
    <div className="space-y-5">
      <section className="rounded-md border border-ink-200 bg-white p-4 shadow-panel">
        <h2 className="text-lg font-semibold">{t("page.settings.title")}</h2>
      </section>
      <div className="grid gap-5 xl:grid-cols-2">
        <section className="rounded-md border border-ink-200 bg-white p-4 shadow-panel">
          <h3 className="mb-3 text-base font-semibold">{t("page.settings.api")}</h3>
          <dl className="space-y-3 text-sm">
            <Row label={t("page.settings.baseUrl")} value={config?.api_base_url ?? "-"} />
            <Row label={t("page.settings.database")} value={config?.database.db_path ?? "-"} />
            <div className="flex items-center justify-between gap-3">
              <dt className="text-ink-500">{t("page.settings.databaseStatus")}</dt>
              <dd>
                <StatusBadge status={config?.database.available ? "available" : "missing"} />
              </dd>
            </div>
            <div className="flex items-center justify-between gap-3">
              <dt className="text-ink-500">{t("page.settings.readOnly")}</dt>
              <dd className="font-mono">{String(config?.database.read_only ?? "-")}</dd>
            </div>
          </dl>
        </section>
        <section className="rounded-md border border-ink-200 bg-white p-4 shadow-panel">
          <h3 className="mb-3 text-base font-semibold">{t("page.settings.uiRunner")}</h3>
          <dl className="space-y-3 text-sm">
            <div className="flex items-center justify-between gap-3">
              <dt className="text-ink-500">{t("page.settings.status")}</dt>
              <dd>
                <StatusBadge status={config?.ui_runner.enabled ? "runner enabled" : "runner disabled"} />
              </dd>
            </div>
            <Row label={t("page.settings.historyDir")} value={config?.ui_runner.history_dir ?? "-"} />
            <Row label={t("page.settings.logDir")} value={config?.ui_runner.log_dir ?? "-"} />
            <Row label={t("page.settings.allowedCommands")} value={config?.ui_runner.allowed_commands.join(", ") ?? "-"} />
            <Row label={t("page.settings.confirmation")} value={String(config?.ui_runner.require_confirmation ?? "-")} />
          </dl>
        </section>
      </div>
      <section className="rounded-md border border-ink-200 bg-white p-4 shadow-panel">
        <h3 className="mb-3 text-base font-semibold">{t("page.settings.researchNotices")}</h3>
        <ul className="space-y-2">
          {(config?.research_notices ?? []).map((notice) => (
            <li key={notice} className="rounded-md border border-ink-200 px-3 py-2 text-sm text-ink-700">
              {notice}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <dt className="text-ink-500">{label}</dt>
      <dd className="break-all text-right font-mono text-xs">{value}</dd>
    </div>
  );
}
