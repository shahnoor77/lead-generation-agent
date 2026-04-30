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
  { key: "QUALIFIED",         label: "Qualified",      color: "border-green-300" },
  { key: "OUTREACH_DRAFTED",  label: "Drafted",        color: "border-purple-300" },
  { key: "READY_FOR_REVIEW",  label: "Review",         color: "border-yellow-300" },
  { key: "READY_TO_SEND",     label: "Ready to Send",  color: "border-orange-300" },
  { key: "CONTACTED",         label: "Contacted",      color: "border-cyan-300" },
  { key: "REPLIED",           label: "Replied",        color: "border-teal-300" },
  { key: "MEETING_SCHEDULED", label: "Meeting",        color: "border-indigo-300" },
  { key: "WON",               label: "Won",            color: "border-emerald-300" },
  { key: "LOST",              label: "Lost",           color: "border-red-300" },
];

const POLL_INTERVAL = 8000;

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
      return true;
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchData().then((done) => {
      if (!done) {
        pollRef.current = setInterval(async () => {
          const complete = await fetchData();
          if (complete && pollRef.current) {
            clearInterval(pollRef.current);
            pollRef.current = null;
          }
        }, POLL_INTERVAL);
      }
    });
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
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

  // Group leads by status
  const byStatus: Record<string, LeadSummary[]> = {};
  for (const col of KANBAN_COLS) byStatus[col.key] = [];
  for (const lead of leads) {
    const key = lead.current_status ?? "QUALIFIED";
    if (byStatus[key]) byStatus[key].push(lead);
  }

  return (
    <div className="flex flex-col h-[calc(100vh-64px)] overflow-hidden">
      {/* Header */}
      <div className="flex-shrink-0 mb-4">
        <div className="flex items-start justify-between">
          <div>
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
          {/* Link to Discovered Leads page */}
          <Link
            href={`/runs/${runId}/discovered`}
            className="text-sm bg-gray-100 hover:bg-gray-200 text-gray-700 px-3 py-1.5 rounded-md font-medium"
          >
            All Discovered ({run.total_discovered}) →
          </Link>
        </div>
      </div>

      {/* Metric cards */}
      <div className="flex-shrink-0 grid grid-cols-4 sm:grid-cols-8 gap-3 mb-4">
        {metrics.map((m) => (
          <MetricCard key={m.label} label={m.label} value={m.value} color={m.color} />
        ))}
      </div>

      {/* Kanban — fills remaining height, columns scroll independently */}
      {leads.length === 0 ? (
        <div className="flex-1 flex flex-col items-center justify-center text-gray-400">
          {pipelineComplete
            ? "No qualified leads found in this run."
            : "Pipeline is running — leads will appear here as they are processed."}
          {!pipelineComplete && (
            <div className="mt-4">
              <div className="w-5 h-5 border-2 border-gray-300 border-t-blue-500 rounded-full animate-spin" />
            </div>
          )}
        </div>
      ) : (
        <div className="flex-1 overflow-x-auto overflow-y-hidden">
          <div className="flex gap-3 h-full min-w-max pb-2">
            {KANBAN_COLS.map((col) => {
              const colLeads = byStatus[col.key] ?? [];
              return (
                <div key={col.key} className={`w-52 flex-shrink-0 flex flex-col border-t-2 ${col.color}`}>
                  {/* Column header — sticky */}
                  <div className="flex items-center justify-between py-2 bg-gray-50 px-1 flex-shrink-0">
                    <span className="text-xs font-semibold text-gray-600 uppercase tracking-wide">
                      {col.label}
                    </span>
                    <span className={`text-xs font-bold px-1.5 py-0.5 rounded-full ${
                      colLeads.length > 0 ? "bg-gray-200 text-gray-700" : "text-gray-300"
                    }`}>
                      {colLeads.length}
                    </span>
                  </div>

                  {/* Scrollable card list */}
                  <div className="flex-1 overflow-y-auto space-y-2 pr-0.5 pt-1">
                    {colLeads.length === 0 && (
                      <div className="border border-dashed border-gray-200 rounded-md h-14 flex items-center justify-center text-xs text-gray-300">
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
      <p className="text-sm font-medium text-gray-900 truncate" title={lead.company_name}>
        {lead.company_name}
      </p>
      <p className="text-xs text-gray-400 truncate mt-0.5">{lead.location}</p>
      <div className="flex items-center justify-between mt-2">
        <span className="text-xs text-gray-500">
          Score: <strong className="text-gray-800">{lead.fit_score}</strong>
        </span>
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
