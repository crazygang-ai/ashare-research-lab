import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  useReactTable
} from "@tanstack/react-table";

import type { ArtifactRecord } from "../api/client";

const columnHelper = createColumnHelper<ArtifactRecord>();

const columns = [
  columnHelper.accessor("kind", {
    header: "Kind",
    cell: (info) => <span className="font-medium">{String(info.getValue())}</span>
  }),
  columnHelper.accessor("artifact_id", {
    header: "Artifact ID",
    cell: (info) => <span className="font-mono text-xs">{String(info.getValue())}</span>
  }),
  columnHelper.accessor("run_id", {
    header: "Run ID",
    cell: (info) => <span className="font-mono text-xs">{String(info.getValue() ?? "-")}</span>
  }),
  columnHelper.accessor("as_of_date", {
    header: "As Of",
    cell: (info) => String(info.getValue() ?? "-")
  }),
  columnHelper.accessor("path", {
    header: "Path",
    cell: (info) => <span className="font-mono text-xs">{String(info.getValue())}</span>
  })
];

export default function ArtifactTable({ artifacts }: { artifacts: ArtifactRecord[] }) {
  const table = useReactTable({
    data: artifacts,
    columns,
    getCoreRowModel: getCoreRowModel()
  });

  if (!artifacts.length) {
    return <p className="rounded-md border border-dashed border-ink-300 bg-white p-4 text-sm text-ink-500">No artifacts found.</p>;
  }

  return (
    <div className="table-scroll overflow-x-auto rounded-md border border-ink-200 bg-white shadow-panel">
      <table className="min-w-full divide-y divide-ink-200 text-left text-sm">
        <thead className="bg-ink-100 text-xs uppercase text-ink-500">
          {table.getHeaderGroups().map((headerGroup) => (
            <tr key={headerGroup.id}>
              {headerGroup.headers.map((header) => (
                <th key={header.id} className="px-3 py-3 font-semibold">
                  {flexRender(header.column.columnDef.header, header.getContext())}
                </th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody className="divide-y divide-ink-100">
          {table.getRowModel().rows.map((row) => (
            <tr key={row.id} className="hover:bg-ink-50">
              {row.getVisibleCells().map((cell) => (
                <td key={cell.id} className="max-w-[28rem] px-3 py-3 align-top">
                  <div className="break-words">{flexRender(cell.column.columnDef.cell, cell.getContext())}</div>
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
