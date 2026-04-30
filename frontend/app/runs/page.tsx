"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { api, PipelineRun } from "@/lib/api";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorMsg } from "@/components/ui/ErrorMsg";

export default function RunsPage() {
  const [runs, setRuns] = useState<PipelineRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    const load = () =>
      api.getRuns()
        .then((r) => setRuns(r.runs))
        .catch((e) => setError(e.message))
        .finally(() => setLoading(false));

    load();

    // Refresh every 10s so in-progress runs update automatically
    const interval = setInterval(load, 10_000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-lg font-semibold">Pipeline Runs</h1>
        <Link href="/runs/new" className="bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium px-4 py-2 rounded-md">
          + New Run
        </Link>
      </div>

      {loading && <Spinner />}
      {error && <ErrorMsg message={error} />}
      {!loading && !error && runs.length === 0 && (
        <p className="text-sm text-gray-500">No runs yet. Start one above.</p>
      )}

      {!loading && runs.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="border-b border-gray-200 text-left text-xs text-gray-500 uppercase tracking-wide">
                <th className="pb-2 pr-4">Industries</th>
                <th className="pb-2 pr-4">Location</th>
                <th className="pb-2 pr-4">Started</th>
                <th className="pb-2 pr-4">Discovered</th>
                <th className="pb-2 pr-4">Status</th>
                <th className="pb-2" />
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.run_id} className="border-b border-gray-100 hover:bg-gray-50">
                  <td className="py-3 pr-4 font-medium text-gray-900">
                    {run.industries}
                    {run.domain && <span className="ml-1 text-gray-400 font-normal">· {run.domain}</span>}
                  </td>
                  <td className="py-3 pr-4 text-gray-600">
                    {run.location}{run.country ? `, ${run.country}` : ""}
                  </td>
                  <td className="py-3 pr-4 text-gray-500">
                    {new Date(run.started_at).toLocaleDateString()}
                  </td>
                  <td className="py-3 pr-4 text-gray-600">{run.total_discovered}</td>
                  <td className="py-3 pr-4">
                    {run.completed_at ? (
                      <RunStatusPills s={run.status_summary} />
                    ) : (
                      <span className="flex items-center gap-1.5 text-xs text-blue-600">
                        <span className="w-1.5 h-1.5 bg-blue-500 rounded-full animate-pulse" />
                        Running…
                      </span>
                    )}
                  </td>
                  <td className="py-3 text-right">
                    <Link href={`/runs/${run.run_id}`} className="text-blue-600 hover:underline text-xs font-medium">
                      Open →
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function RunStatusPills({ s }: { s: PipelineRun["status_summary"] }) {
  const pills = [
    { label: "Qualified", value: s.total_qualified, color: "bg-green-100 text-green-700" },
    { label: "Review", value: s.total_ready_for_review, color: "bg-yellow-100 text-yellow-700" },
    { label: "Contacted", value: s.total_contacted, color: "bg-cyan-100 text-cyan-700" },
    { label: "Meetings", value: s.total_meetings, color: "bg-indigo-100 text-indigo-700" },
    { label: "Won", value: s.total_won, color: "bg-emerald-100 text-emerald-700" },
  ].filter((p) => p.value > 0);

  if (pills.length === 0) return <span className="text-gray-400 text-xs">—</span>;
  return (
    <div className="flex flex-wrap gap-1">
      {pills.map((p) => (
        <span key={p.label} className={`text-xs px-1.5 py-0.5 rounded font-medium ${p.color}`}>
          {p.label}: {p.value}
        </span>
      ))}
    </div>
  );
}
