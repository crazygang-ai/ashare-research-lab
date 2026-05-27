export type ResearchFlags = {
  research_only?: boolean;
  not_trading_instruction?: boolean;
};

export type UiConfig = ResearchFlags & {
  api_base_url: string;
  database: {
    db_path: string;
    read_only: boolean;
    available: boolean;
  };
  artifact_roots: string[];
  ui_runner: {
    enabled: boolean;
    history_dir: string;
    log_dir: string;
    allowed_commands: string[];
    require_confirmation: boolean;
  };
  research_notices: string[];
};

export type ArtifactRecord = {
  artifact_id: string;
  kind: string;
  path: string;
  run_id?: string | null;
  as_of_date?: string | null;
  created_at?: string | null;
  rows?: number | null;
  [key: string]: unknown;
};

export type UiRunStatus = "queued" | "running" | "success" | "failed" | "cancelled";

export type UiRunRecord = {
  ui_run_id: string;
  task_type: "stock-report" | "hs300-daily" | string;
  status: UiRunStatus;
  params: Record<string, unknown>;
  command_preview: string[];
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  steps: Array<Record<string, unknown>>;
  log_paths: string[];
  artifact_paths: string[];
  error_code?: string | null;
  error_message?: string | null;
};

export type CsvPayload = ResearchFlags & {
  rows: Array<Record<string, unknown>>;
  columns?: string[];
  artifact_id?: string;
  path?: string;
  [key: string]: unknown;
};

export type RunListPayload = ResearchFlags & {
  runs: Array<Record<string, unknown>>;
};

export type ArtifactListPayload = ResearchFlags & {
  artifacts: ArtifactRecord[];
};

export type UiRunListPayload = ResearchFlags & {
  runs: UiRunRecord[];
};

export type UiRunPayload = ResearchFlags & {
  run: UiRunRecord;
};

export type StockReportRequest = {
  stock_code: string;
  as_of: string;
  source_run_id: string;
  score_run_id: string;
  scan_run_id?: string;
  db_path: string;
  output_dir: string;
  run_id: string;
  confirmed: boolean;
};

export type Hs300DailyRequest = {
  as_of: string;
  stock_code: string;
  cache_mode: "use" | "refresh" | "offline";
  max_symbols?: number;
  watchlist_file?: string;
  confirmed: boolean;
};

export class ApiError extends Error {
  status: number;
  errorCode?: string;

  constructor(message: string, status: number, errorCode?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.errorCode = errorCode;
  }
}

const API_BASE_URL = import.meta.env.VITE_ASHARE_API_BASE_URL ?? "";

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers
    }
  });
  const payload = (await response.json().catch(() => ({}))) as {
    message?: string;
    error_code?: string;
  };
  if (!response.ok) {
    throw new ApiError(payload.message ?? response.statusText, response.status, payload.error_code);
  }
  return payload as T;
}

async function requestText(path: string): Promise<string> {
  const response = await fetch(`${API_BASE_URL}${path}`);
  if (!response.ok) {
    throw new ApiError(response.statusText, response.status);
  }
  return response.text();
}

export function fetchUiConfig() {
  return requestJson<UiConfig>("/api/v1/ui/config");
}

export function fetchArtifacts(kind?: string) {
  const query = kind ? `?kind=${encodeURIComponent(kind)}&limit=100` : "?limit=100";
  return requestJson<ArtifactListPayload>(`/api/v1/artifacts${query}`);
}

export function fetchRuns() {
  return requestJson<RunListPayload>("/api/v1/runs?limit=100");
}

export function fetchUiRuns() {
  return requestJson<UiRunListPayload>("/api/v1/ui/runs?limit=100");
}

export function fetchUiRun(uiRunId: string) {
  return requestJson<UiRunPayload>(`/api/v1/ui/runs/${encodeURIComponent(uiRunId)}`);
}

export function fetchLatestScan() {
  return requestJson<CsvPayload>("/api/v1/scans/latest");
}

export function fetchLatestScoring() {
  return requestJson<CsvPayload>("/api/v1/scoring/latest");
}

export function fetchLatestDailyReportMarkdown() {
  return requestText("/api/v1/reports/daily/latest/markdown");
}

export function fetchLatestStockReportMarkdown() {
  return requestText("/api/v1/reports/stocks/latest/markdown");
}

export function fetchStockFactors(stockCode: string, asOf: string, sourceRunId: string) {
  const params = new URLSearchParams({ as_of: asOf, source_run_id: sourceRunId });
  return requestJson<CsvPayload>(
    `/api/v1/stocks/${encodeURIComponent(stockCode)}/factors?${params.toString()}`
  );
}

export function createStockReportRun(payload: StockReportRequest) {
  return requestJson<UiRunPayload>("/api/v1/ui/runs/stock-report", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function createHs300DailyRun(payload: Hs300DailyRequest) {
  return requestJson<UiRunPayload>("/api/v1/ui/runs/hs300-daily", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function executeUiRun(uiRunId: string) {
  return requestJson<UiRunPayload>(`/api/v1/ui/runs/${encodeURIComponent(uiRunId)}/execute`, {
    method: "POST",
    body: JSON.stringify({})
  });
}
