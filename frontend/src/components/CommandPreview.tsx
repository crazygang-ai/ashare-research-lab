import { Copy } from "lucide-react";

import { useI18n } from "../i18n";

export default function CommandPreview({ command }: { command?: string[] }) {
  const { t } = useI18n();
  const text = command?.join(" ") ?? "";

  return (
    <div className="rounded-md border border-ink-200 bg-white shadow-panel">
      <div className="flex items-center justify-between gap-3 border-b border-ink-200 px-4 py-3">
        <h2 className="text-sm font-semibold">{t("component.commandPreview.title")}</h2>
        <button
          type="button"
          aria-label={t("component.commandPreview.copyCommand")}
          title={t("component.commandPreview.copyCommand")}
          className="inline-flex min-h-11 items-center gap-2 rounded-md border border-ink-300 px-3 py-2 text-sm hover:bg-ink-100"
          onClick={() => void navigator.clipboard?.writeText(text)}
          disabled={!text}
        >
          <Copy className="h-4 w-4" aria-hidden="true" />
          {t("component.commandPreview.copy")}
        </button>
      </div>
      <pre className="table-scroll max-h-48 overflow-auto p-4 font-mono text-xs leading-5 text-ink-700">
        {text || t("component.commandPreview.empty")}
      </pre>
    </div>
  );
}
