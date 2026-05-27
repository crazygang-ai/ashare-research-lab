import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  BarChart3,
  Database,
  FileText,
  Home,
  ListChecks,
  Settings,
  ShieldCheck
} from "lucide-react";
import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";

import { fetchUiConfig } from "../api/client";
import { useI18n, type Language, type TranslationKey } from "../i18n";
import StatusBadge from "./StatusBadge";

type NavItem = {
  labelKey: TranslationKey;
  to: string;
  icon: typeof Home;
};

const navItems: NavItem[] = [
  { labelKey: "nav.today", to: "/", icon: Home },
  { labelKey: "nav.stocks", to: "/stocks", icon: BarChart3 },
  { labelKey: "nav.reports", to: "/reports", icon: FileText },
  { labelKey: "nav.runs", to: "/runs", icon: ListChecks },
  { labelKey: "nav.artifacts", to: "/artifacts", icon: Database },
  { labelKey: "nav.settings", to: "/settings", icon: Settings }
];

const languageOptions: Array<{ value: Language; label: string }> = [
  { value: "zh", label: "中文" },
  { value: "en", label: "English" }
];

export default function AppShell({ children }: { children: ReactNode }) {
  const { language, setLanguage, t } = useI18n();
  const configQuery = useQuery({ queryKey: ["ui-config"], queryFn: fetchUiConfig });
  const config = configQuery.data;
  const notices = config?.research_notices ?? [
    "candidate list is not a trading instruction",
    "composite score is not a trading instruction",
    "stock report is for research review only"
  ];

  return (
    <div className="min-h-dvh bg-ink-50 text-ink-900">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-white focus:px-3 focus:py-2"
      >
        {t("app.skipToContent")}
      </a>
      <div className="flex min-h-dvh flex-col lg:flex-row">
        <aside className="border-b border-ink-200 bg-white lg:fixed lg:inset-y-0 lg:left-0 lg:w-64 lg:border-b-0 lg:border-r">
          <div className="flex h-16 items-center gap-3 px-4">
            <div className="flex h-10 w-10 items-center justify-center rounded-md bg-ink-900 text-white">
              <Activity className="h-5 w-5" aria-hidden="true" />
            </div>
            <div>
              <h1 className="text-base font-semibold">{t("app.title")}</h1>
              <p className="text-xs text-ink-500">{t("app.subtitle")}</p>
            </div>
          </div>
          <nav className="flex gap-1 overflow-x-auto px-3 pb-3 lg:block lg:space-y-1 lg:overflow-visible">
            {navItems.map((item) => {
              const Icon = item.icon;
              return (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.to === "/"}
                  className={({ isActive }) =>
                    [
                      "flex min-h-11 items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition",
                      isActive
                        ? "bg-ink-900 text-white"
                        : "text-ink-700 hover:bg-ink-100 hover:text-ink-900"
                    ].join(" ")
                  }
                >
                  <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
                  <span>{t(item.labelKey)}</span>
                </NavLink>
              );
            })}
          </nav>
        </aside>

        <div className="flex min-w-0 flex-1 flex-col lg:pl-64">
          <header className="sticky top-0 z-20 border-b border-ink-200 bg-white/95 px-4 py-3 backdrop-blur sm:px-6">
            <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
              <div className="flex flex-wrap items-center gap-2">
                <ShieldCheck className="h-4 w-4 text-signal-teal" aria-hidden="true" />
                {notices.slice(0, 3).map((notice) => (
                  <span key={notice} className="rounded-md border border-ink-200 px-2 py-1 text-xs text-ink-700">
                    {notice}
                  </span>
                ))}
              </div>
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <div
                  className="inline-flex rounded-md border border-ink-300 bg-ink-100 p-1"
                  role="group"
                  aria-label={t("language.switcher")}
                >
                  {languageOptions.map((option) => (
                    <button
                      key={option.value}
                      type="button"
                      className={[
                        "min-h-8 rounded px-2 text-xs font-medium",
                        language === option.value
                          ? "bg-white text-ink-900 shadow-panel"
                          : "text-ink-600 hover:text-ink-900"
                      ].join(" ")}
                      aria-pressed={language === option.value}
                      onClick={() => setLanguage(option.value)}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
                <StatusBadge status={config?.database.available ? "available" : "missing"} />
                <StatusBadge status={config?.ui_runner.enabled ? "runner enabled" : "runner disabled"} />
              </div>
            </div>
          </header>

          <main id="main-content" className="flex-1 px-4 py-5 sm:px-6 lg:px-8">
            {children}
          </main>
        </div>
      </div>
    </div>
  );
}
