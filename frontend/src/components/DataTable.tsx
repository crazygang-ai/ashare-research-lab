import { useI18n } from "../i18n";

type DataTableProps = {
  rows?: Array<Record<string, unknown>>;
  maxRows?: number;
};

export default function DataTable({ rows = [], maxRows = 20 }: DataTableProps) {
  const { t } = useI18n();
  const visibleRows = rows.slice(0, maxRows);
  const columns = Array.from(new Set(visibleRows.flatMap((row) => Object.keys(row)))).slice(0, 12);

  if (!visibleRows.length || !columns.length) {
    return <p className="rounded-md border border-dashed border-ink-300 bg-white p-4 text-sm text-ink-500">{t("component.dataTable.empty")}</p>;
  }

  return (
    <div className="table-scroll overflow-x-auto rounded-md border border-ink-200 bg-white shadow-panel">
      <table className="min-w-full divide-y divide-ink-200 text-left text-sm">
        <thead className="bg-ink-100 text-xs uppercase text-ink-500">
          <tr>
            {columns.map((column) => (
              <th key={column} className="px-3 py-3 font-semibold">
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-ink-100">
          {visibleRows.map((row, rowIndex) => (
            <tr key={rowIndex} className="hover:bg-ink-50">
              {columns.map((column) => (
                <td key={column} className="max-w-64 px-3 py-3 align-top">
                  <span className="break-words font-mono text-xs">{formatValue(row[column])}</span>
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function formatValue(value: unknown) {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  if (typeof value === "number") {
    return Number.isInteger(value) ? String(value) : value.toFixed(4);
  }
  return String(value);
}
