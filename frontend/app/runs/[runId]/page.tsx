"use client";
import { useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { api, LeadSummary, PipelineRun } from "@/lib/api";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorMsg } from "@/components/ui/ErrorMsg";
import { MetricCard } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";

const KANBAN_COLS = [
  { key: "QUALIFIED",         label: "Qualified" },
  { key: "OUTREACH_DRAFTED",  label: "Drafted" },
  { key: "READY_FOR_REVIEW",  label: "Review" },
  { key: "READY_TO_SEND",     label: "Ready to Send" },
  { key: "CONTACTED",         label: "Contacted" },
  { key: "REPLIED",           label: "Replied" },
  { key: "MEETING_SCHEDULED", label: "Meeting" },
  { key: "WON",               label: "Won" },
  { key: "LOST",              label: "Lost" },
];

const POLL_INTERVAL = 8000; // ms — poll every 8s while pipeline is running

export default function RunDetailPage() {
  const { runId } = useParams<{ runId: string }>();
  const [run, setRun] = useState<PipelineRun | null>(null);
  const [leads, setLeads] = useState<LeadSummary[]>([]);
  const [pipelineComplete, setPipelineComplete] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  async function fetchData() {
    try {
      const [runsRes, leadsRes] = await Promise.all([
        api.getRuns(),
        api.getRunLeads(runId),
      ]);
      const found = runsRes.runs.find((r) => r.run_id === runId) ?? null;
      setRun(found);
      setLeads(leadsRes.leads);
      setPipelineComplete(leadsRes.pipeline_complete);
      return leadsRes.pipeline_complete;
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load run");
      return true; // stop polling on error
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchData().then((done) => {
      if (!done) {
        // Pipeline still running — poll until complete
        pollRef.current = setInterval(async () => {
          const complete = await fetchData();
          if (complete && pollRef.current) {
            clearInterval(pollRef.current);
            pollRef.current = null;
          }
        }, POLL_INTERVAL);
      }
    });
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [runId]);

  if (loading) return <Spinner />;
  if (error) return <ErrorMsg message={error} />;
  if (!run) return <ErrorMsg message="Run not found." />;

  const s = run.status_summary;
  const metrics = [
    { label: "Discovered",  value: run.total_discovered },
    { label: "Qualified",   value: s.total_qualified,        color: "text-green-600" },
    { label: "Review",      value: s.total_ready_for_review, color: "text-yellow-600" },
    { label: "Contacted",   value: s.total_contacted,        color: "text-cyan-600" },
    { label: "Replied",     value: s.total_replied,          color: "text-teal-600" },
    { label: "Meetings",    value: s.total_meetings,         color: "text-indigo-600" },
    { label: "Won",         value: s.total_won,              color: "text-emerald-600" },
    { label: "Lost",        value: s.total_lost,             color: "text-red-500" },
  ];

  const byStatus: Record<string, LeadSummary[]> = {};
  for (const col of KANBAN_COLS) byStatus[col.key] = [];
  for (const lead of leads) {
    const key = lead.current_status ?? "QUALIFIED";
    if (byStatus[key]) byStatus[key].push(lead);
  }

  return (
    <div>
      {/* Header */}
      <div className="mb-6">
        <div className="text-xs text-gray-400 mb-1">
          <Link href="/runs" className="hover:underline">Runs</Link> / {run.industries}
        </div>
        <div className="flex items-center gap-3">
          <h1 className="text-lg font-semibold">
            {run.industries}
            {run.domain && <span className="text-gray-400 font-normal ml-2 text-base">· {run.domain}</span>}
          </h1>
          {!pipelineComplete && (
            <span className="flex items-center gap-1.5 text-xs text-blue-600 bg-blue-50 border border-blue-200 px-2 py-0.5 rounded-full">
              <span className="w-1.5 h-1.5 bg-blue-500 rounded-full animate-pulse" />
              Pipeline running…
            </span>
          )}
        </div>
        <p className="text-sm text-gray-500 mt-0.5">
          {run.location}{run.country ? `, ${run.country}` : ""} · {new Date(run.started_at).toLocaleDateString()}
        </p>
      </div>

      {/* Metric cards */}
      <div className="grid grid-cols-4 sm:grid-cols-8 gap-3 mb-8">
        {metrics.map((m) => (
          <MetricCard key={m.label} label={m.label} value={m.value} color={m.color} />
        ))}
      </div>

      {/* Kanban */}
      {leads.length === 0 ? (
        <div className="text-center py-16 text-gray-400">
          {pipelineComplete
            ? "No qualified leads found in this run."
            : "Pipeline is running — leads will appear here as they are processed."}
          {!pipelineComplete && (
            <div className="mt-4 flex justify-center">
              <div className="w-5 h-5 border-2 border-gray-300 border-t-blue-500 rounded-full animate-spin" />
            </div>
          )}
        </div>
      ) : (
        <div className="overflow-x-auto pb-4">
          <div className="flex gap-3 min-w-max">
            {KANBAN_COLS.map((col) => {
              const colLeads = byStatus[col.key] ?? [];
              return (
                <div key={col.key} className="w-52 flex-shrink-0">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs font-semibold text-gray-600 uppercase tracking-wide">{col.label}</span>
                    <span className="text-xs text-gray-400">{colLeads.length}</span>
                  </div>
                  <div className="space-y-2">
                    {colLeads.length === 0 && (
                      <div className="border border-dashed border-gray-200 rounded-md h-16 flex items-center justify-center text-xs text-gray-300">
                        empty
                      </div>
                    )}
                    {colLeads.map((lead) => (
                      <KanbanCard key={lead.lead_id} lead={lead} />
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

function KanbanCard({ lead }: { lead: LeadSummary }) {
  return (
    <div className="bg-white border border-gray-200 rounded-md p-3 shadow-sm">
      <p className="text-sm font-medium text-gray-900 truncate">{lead.company_name}</p>
      <div className="flex items-center justify-between mt-1.5">
        <span className="text-xs text-gray-500">Score: <strong>{lead.fit_score}</strong></span>
        {lead.approval_status && <Badge label={lead.approval_status} />}
      </div>
      <Link
        href={`/leads/${lead.lead_id}`}
        className="mt-2 block text-center text-xs text-blue-600 hover:underline font-medium"
      >
        Open →
      </Link>
    </div>
  );
}
