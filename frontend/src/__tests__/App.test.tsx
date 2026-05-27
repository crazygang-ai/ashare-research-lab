import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import App from "../App";

const mockConfig = {
  research_only: true,
  not_trading_instruction: true,
  api_base_url: "http://127.0.0.1:8008",
  database: {
    db_path: "data/processed/hs300_daily.duckdb",
    read_only: true,
    available: false
  },
  artifact_roots: ["data/reports/generated"],
  ui_runner: {
    enabled: false,
    history_dir: "data/service/workflow-runs",
    log_dir: "data/service/workflow-logs",
    allowed_commands: ["stock-report", "hs300-daily"],
    require_confirmation: true
  },
  research_notices: [
    "candidate list is not a trading instruction",
    "stock report is for research review only"
  ]
};

const mockUiRun = {
  ui_run_id: "run-raw-status",
  task_type: "stock-report",
  status: "running" as const,
  params: {},
  command_preview: [],
  created_at: "2026-05-27T00:00:00Z",
  started_at: "2026-05-27T00:00:00Z",
  finished_at: null,
  steps: [],
  log_paths: [],
  artifact_paths: []
};

vi.mock("../api/client", () => ({
  fetchUiConfig: vi.fn(async () => mockConfig),
  fetchArtifacts: vi.fn(async () => ({ artifacts: [] })),
  fetchRuns: vi.fn(async () => ({ runs: [] })),
  fetchUiRuns: vi.fn(async () => ({ runs: [mockUiRun] })),
  fetchUiRun: vi.fn(async () => ({ run: mockUiRun })),
  fetchLatestDailyReportMarkdown: vi.fn(async () => "# Daily Research Report"),
  fetchLatestStockReportMarkdown: vi.fn(async () => "# Stock Research Report"),
  fetchLatestScoring: vi.fn(async () => ({ rows: [] })),
  fetchLatestScan: vi.fn(async () => ({ rows: [] })),
  fetchStockFactors: vi.fn(async () => ({ rows: [] })),
  createHs300DailyRun: vi.fn(async () => ({ run: { ui_run_id: "run-1", command_preview: [] } })),
  createStockReportRun: vi.fn(async () => ({ run: { ui_run_id: "run-2", command_preview: [] } })),
  executeUiRun: vi.fn(async () => ({ run: { ui_run_id: "run-1", command_preview: [] } }))
}));

function renderApp(initialPath = "/") {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } }
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialPath]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("App", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("renders Chinese UI by default and keeps backend notices unchanged", async () => {
    renderApp();

    expect(await screen.findByText("A 股研究工作台")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /今日/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /个股/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /报告/ })).toBeInTheDocument();
    expect(screen.getByText("stock report is for research review only")).toBeInTheDocument();
  });

  it("opens the settings page from a deep link in Chinese", async () => {
    renderApp("/settings");

    expect(await screen.findByRole("heading", { name: "设置" })).toBeInTheDocument();
    expect(await screen.findByText("http://127.0.0.1:8008")).toBeInTheDocument();
  });

  it("switches to English and persists the selected language", async () => {
    const firstRender = renderApp("/settings");

    fireEvent.click(await screen.findByRole("button", { name: "English" }));

    expect(await screen.findByRole("heading", { name: "Settings" })).toBeInTheDocument();
    expect(window.localStorage.getItem("ashare-ui-language")).toBe("en");

    firstRender.unmount();
    renderApp("/settings");

    expect(await screen.findByRole("heading", { name: "Settings" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Today/ })).toBeInTheDocument();
  });

  it("keeps backend run statuses raw in Chinese UI", async () => {
    renderApp("/runs");

    const rawStatuses = await screen.findAllByText("running");

    expect(rawStatuses.length).toBeGreaterThan(0);
    expect(screen.queryByText("运行中")).not.toBeInTheDocument();
  });
});
