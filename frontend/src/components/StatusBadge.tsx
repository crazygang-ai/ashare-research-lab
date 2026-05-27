type StatusBadgeProps = {
  status?: string | null;
};

const colorByStatus: Record<string, string> = {
  success: "border-emerald-200 bg-emerald-50 text-emerald-800",
  running: "border-blue-200 bg-blue-50 text-blue-800",
  queued: "border-amber-200 bg-amber-50 text-amber-800",
  failed: "border-red-200 bg-red-50 text-red-800",
  cancelled: "border-ink-200 bg-ink-100 text-ink-700",
  available: "border-emerald-200 bg-emerald-50 text-emerald-800",
  missing: "border-red-200 bg-red-50 text-red-800",
  "runner enabled": "border-blue-200 bg-blue-50 text-blue-800",
  "runner disabled": "border-amber-200 bg-amber-50 text-amber-800"
};

export default function StatusBadge({ status }: StatusBadgeProps) {
  const normalized = (status ?? "unknown").toLowerCase();
  const color = colorByStatus[normalized] ?? "border-ink-200 bg-white text-ink-700";
  return (
    <span className={`inline-flex min-h-7 items-center rounded-md border px-2 py-1 text-xs font-medium ${color}`}>
      {status ?? "unknown"}
    </span>
  );
}
