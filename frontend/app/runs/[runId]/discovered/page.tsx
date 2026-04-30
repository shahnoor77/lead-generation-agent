"use client";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { api, DiscoveredLead } from "@/lib/api";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorMsg } from "@/components/ui/ErrorMsg";
import { Badge } from "@/components/ui/Badge";

export default function DiscoveredPage() {
  const { runId } = useParams<{ runId: string }>();
  const [leads, setLeads] = useState<DiscoveredLead[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState<"all" | "qualified" | "rejected">("all");
  const [search, setSearch] = useState("");

  useEffect(() => {
    api.getRunDiscovered(runId)
      .then((r) => { setLeads(r.leads); setTotal(r.total); })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [runId]);

  const filtered = leads.filter((l) => {
    const matchFilter =
      filter === "all" ||
      (filter === "qualified" && l.icp_decision === "QUALIFIED") ||
      (filter === "rejected" && l.icp_decision === "REJECTED");
    const matchSearch =
      !search ||
      l.company_name.toLowerCase().includes(search.toLowerCase()) ||
      (l.category ?? "").toLowerCase().includes(search.toLowerCase()) ||
      (l.location ?? "").toLowerCase().includes(search.toLowerCase());
    return matchFilter && matchSearch;
  });

  const qualified = leads.filter((l) => l.icp_decision === "QUALIFIED").length;
  const rejected  = leads.filter((l) => l.icp_decision === "REJECTED").length;
  const pending   = leads.filter((l) => !l.icp_decision).length;

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <div className="text-xs text-gray-400 mb-1">
            <Link href="/runs" className="hover:underline">Runs</Link>
            {" / "}
            <Link href={`/runs/${runId}`} className="hover:underline">Run</Link>
            {" / Discovered Leads"}
          </div>
          <h1 className="text-lg font-semibold">Discovered Leads</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            {total} total · {qualified} qualified · {rejected} rejected · {pending} pending
          </p>
        </div>
        <Link href={`/runs/${runId}`} className="text-sm text-blue-600 hover:underline">
          ← Back to Run
        </Link>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3 mb-4">
        <div className="flex gap-1 bg-gray-100 rounded-md p-1">
          {(["all", "qualified", "rejected"] as const).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-3 py-1 rounded text-xs font-medium capitalize ${
                filter === f ? "bg-white shadow text-gray-900" : "text-gray-500 hover:text-gray-700"
              }`}
            >
              {f}
            </button>
          ))}
        </div>
        <input
          className="border border-gray-300 rounded-md px-3 py-1.5 text-sm w-56 focus:outline-none focus:ring-1 focus:ring-blue-500"
          placeholder="Search company, category…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <span className="text-xs text-gray-400">{filtered.length} shown</span>
      </div>

      {loading && <Spinner />}
      {error && <ErrorMsg message={error} />}

      {!loading && !error && filtered.length === 0 && (
        <p className="text-sm text-gray-400 py-8 text-center">No leads match the current filter.</p>
      )}

      {!loading && filtered.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="border-b border-gray-200 text-left text-xs text-gray-500 uppercase tracking-wide">
                <th className="pb-2 pr-4 min-w-[180px]">Company</th>
                <th className="pb-2 pr-4">Category / Industry</th>
                <th className="pb-2 pr-4">Location</th>
                <th className="pb-2 pr-4">Website</th>
                <th className="pb-2 pr-4">Phone</th>
                <th className="pb-2 pr-4">Email</th>
                <th className="pb-2 pr-4">LinkedIn</th>
                <th className="pb-2 pr-4">ICP</th>
                <th className="pb-2" />
              </tr>
            </thead>
            <tbody>
              {filtered.map((lead) => (
                <tr key={lead.lead_id} className="border-b border-gray-100 hover:bg-gray-50 align-top">
                  <td className="py-2.5 pr-4">
                    <p className="font-medium text-gray-900">{lead.company_name}</p>
                    {lead.address && (
                      <p className="text-xs text-gray-400 mt-0.5 max-w-[200px] truncate">{lead.address}</p>
                    )}
                  </td>
                  <td className="py-2.5 pr-4 text-gray-600">
                    <p>{lead.category || "—"}</p>
                    {lead.industry && <p className="text-xs text-gray-400">{lead.industry}</p>}
                    {lead.business_type && lead.business_type !== "UNKNOWN" && (
                      <span className="text-xs bg-gray-100 text-gray-500 px-1 rounded">{lead.business_type}</span>
                    )}
                  </td>
                  <td className="py-2.5 pr-4 text-gray-600 text-xs">{lead.location}</td>
                  <td className="py-2.5 pr-4">
                    {lead.website ? (
                      <a href={lead.website} target="_blank" rel="noreferrer"
                        className="text-blue-600 hover:underline text-xs truncate block max-w-[160px]">
                        {lead.website.replace(/^https?:\/\/(www\.)?/, "")}
                      </a>
                    ) : <span className="text-gray-300 text-xs">—</span>}
                  </td>
                  <td className="py-2.5 pr-4 text-xs text-gray-600">
                    {lead.phone || <span className="text-gray-300">—</span>}
                  </td>
                  <td className="py-2.5 pr-4 text-xs">
                    {lead.contact_email ? (
                      <a href={`mailto:${lead.contact_email}`} className="text-blue-600 hover:underline">
                        {lead.contact_email}
                      </a>
                    ) : <span className="text-gray-300">—</span>}
                  </td>
                  <td className="py-2.5 pr-4 text-xs">
                    {lead.linkedin_url ? (
                      <a href={lead.linkedin_url} target="_blank" rel="noreferrer"
                        className="text-blue-600 hover:underline">LinkedIn</a>
                    ) : <span className="text-gray-300">—</span>}
                  </td>
                  <td className="py-2.5 pr-4">
                    {lead.icp_decision ? (
                      <div className="space-y-0.5">
                        <Badge label={lead.icp_decision} />
                        {lead.fit_score != null && (
                          <p className="text-xs text-gray-400">{lead.fit_score}/100</p>
                        )}
                      </div>
                    ) : <span className="text-gray-300 text-xs">pending</span>}
                  </td>
                  <td className="py-2.5 text-right">
                    {lead.icp_decision === "QUALIFIED" && (
                      <Link href={`/leads/${lead.lead_id}`}
                        className="text-xs text-blue-600 hover:underline font-medium">
                        Open →
                      </Link>
                    )}
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
