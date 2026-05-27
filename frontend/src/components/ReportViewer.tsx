import ReactMarkdown from "react-markdown";

type ReportViewerProps = {
  title: string;
  markdown?: string;
  isLoading?: boolean;
  error?: unknown;
};

export default function ReportViewer({ title, markdown, isLoading, error }: ReportViewerProps) {
  return (
    <section className="rounded-md border border-ink-200 bg-white shadow-panel">
      <div className="border-b border-ink-200 px-4 py-3">
        <h2 className="text-sm font-semibold text-ink-900">{title}</h2>
      </div>
      <div className="max-h-[42rem] overflow-auto p-4">
        {isLoading ? <p className="text-sm text-ink-500">Loading...</p> : null}
        {error ? <p className="text-sm text-signal-red">Report is unavailable.</p> : null}
        {markdown ? (
          <ReactMarkdown
            components={{
              h1: ({ children }) => <h3 className="mb-3 text-lg font-semibold">{children}</h3>,
              h2: ({ children }) => <h4 className="mb-2 mt-4 text-base font-semibold">{children}</h4>,
              p: ({ children }) => <p className="mb-3 text-sm leading-6 text-ink-700">{children}</p>,
              li: ({ children }) => <li className="mb-1 text-sm leading-6 text-ink-700">{children}</li>,
              table: ({ children }) => (
                <div className="table-scroll my-3 overflow-x-auto">
                  <table className="min-w-full divide-y divide-ink-200 text-sm">{children}</table>
                </div>
              ),
              th: ({ children }) => <th className="bg-ink-100 px-2 py-2 text-left text-xs font-semibold">{children}</th>,
              td: ({ children }) => <td className="border-b border-ink-100 px-2 py-2 align-top">{children}</td>,
              code: ({ children }) => <code className="rounded bg-ink-100 px-1 py-0.5 font-mono text-xs">{children}</code>
            }}
          >
            {markdown}
          </ReactMarkdown>
        ) : null}
      </div>
    </section>
  );
}
