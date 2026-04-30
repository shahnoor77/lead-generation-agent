"use client";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { api, LeadDetail } from "@/lib/api";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorMsg } from "@/components/ui/ErrorMsg";
import { Badge } from "@/components/ui/Badge";
import { Card } from "@/components/ui/Card";

export default function LeadDetailPage() {
  const { leadId } = useParams<{ leadId: string }>();
  const [lead, setLead] = useState<LeadDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const reload = () => {
    setLoading(true);
    api.getLeadDetail(leadId)
      .then(setLead)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(reload, [leadId]);

  if (loading) return <Spinner />;
  if (error) return <ErrorMsg message={error} />;
  if (!lead) return <ErrorMsg message="Lead not found." />;

  return (
    <div className="max-w-4xl space-y-6">
      {/* Breadcrumb */}
      <div className="text-xs text-gray-400">
        <Link href="/runs" className="hover:underline">Runs</Link>
        {" / "}
        <Link href={`/runs/${lead.pipeline_run_id}`} className="hover:underline">Run</Link>
        {" / "}
        {lead.company.company_name}
      </div>

      {/* Title + status */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-lg font-semibold">{lead.company.company_name}</h1>
          {lead.company.website && (
            <a href={lead.company.website} target="_blank" rel="noreferrer" className="text-sm text-blue-600 hover:underline">
              {lead.company.website}
            </a>
          )}
        </div>
        <div className="flex items-center gap-2">
          {lead.current_status && <Badge label={lead.current_status} />}
          <span className="text-sm font-bold text-gray-700">Score: {lead.intelligence.fit_score}</span>
        </div>
      </div>

      {/* S1 — Company */}
      <Section title="Company">
        <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
          <DL label="Location" value={lead.company.location} />
          <DL label="Category" value={lead.company.category} />
          <DL label="Address" value={lead.company.address} />
          <DL label="Phone" value={lead.company.phone} />
          {lead.company.rating != null && <DL label="Rating" value={`${lead.company.rating} (${lead.company.review_count} reviews)`} />}
        </dl>
      </Section>

      {/* S2 — Intelligence */}
      <Section title="Intelligence">
        <div className="space-y-3 text-sm">
          {lead.intelligence.enrichment_summary && (
            <div>
              <p className="text-xs font-medium text-gray-500 mb-1">Summary</p>
              <p className="text-gray-700">{lead.intelligence.enrichment_summary}</p>
            </div>
          )}
          {lead.intelligence.inferred_pain_points.length > 0 && (
            <div>
              <p className="text-xs font-medium text-gray-500 mb-1">Inferred Pain Points</p>
              <ul className="list-disc list-inside space-y-0.5 text-gray-700">
                {lead.intelligence.inferred_pain_points.map((p, i) => <li key={i}>{p}</li>)}
              </ul>
            </div>
          )}
          {lead.intelligence.icp_reasoning && (
            <div>
              <p className="text-xs font-medium text-gray-500 mb-1">ICP Reasoning</p>
              <p className="text-gray-700">{lead.intelligence.icp_reasoning}</p>
            </div>
          )}
          <div className="flex gap-4 text-xs text-gray-500">
            <span>Rule: <strong>{lead.intelligence.rule_score}</strong></span>
            {lead.intelligence.llm_score != null && <span>LLM: <strong>{lead.intelligence.llm_score}</strong></span>}
            <span>Fit: <strong className="text-gray-900">{lead.intelligence.fit_score}</strong></span>
          </div>
        </div>
      </Section>

      {/* S3 — Draft Review */}
      <Section title="Draft Review">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* Generated — read-only */}
          <div>
            <p className="text-xs font-semibold text-gray-500 mb-2 uppercase tracking-wide">AI Generated (read-only)</p>
            {lead.generated_draft ? (
              <div className="bg-gray-50 border border-gray-200 rounded-md p-3 space-y-2 text-sm">
                <p className="font-medium text-gray-800">{lead.generated_draft.subject}</p>
                <p className="text-gray-600 whitespace-pre-wrap text-xs">{lead.generated_draft.body}</p>
                <p className="text-xs text-gray-400">{lead.generated_draft.word_count} words · {lead.generated_draft.language}</p>
              </div>
            ) : (
              <p className="text-sm text-gray-400">No draft generated yet.</p>
            )}
          </div>
          {/* Final — editable via form below */}
          <div>
            <p className="text-xs font-semibold text-gray-500 mb-2 uppercase tracking-wide">Final Draft</p>
            {lead.final_draft ? (
              <div className="bg-white border border-gray-200 rounded-md p-3 space-y-2 text-sm">
                <p className="font-medium text-gray-800">{lead.final_draft.subject}</p>
                <p className="text-gray-600 whitespace-pre-wrap text-xs">{lead.final_draft.body}</p>
                <div className="flex items-center gap-2">
                  <Badge label={lead.final_draft.approval_status} />
                  {lead.final_draft.finalized_by && <span className="text-xs text-gray-400">by {lead.final_draft.finalized_by}</span>}
                </div>
              </div>
            ) : (
              <p className="text-sm text-gray-400">Not finalized yet. Use the form below.</p>
            )}
          </div>
        </div>
      </Section>

      {/* S4 + S5 — Finalize form */}
      <FinalizeForm lead={lead} onSuccess={reload} />

      {/* Status update */}
      <StatusUpdateForm lead={lead} onSuccess={reload} />

      {/* Status history */}
      {lead.status_history.length > 0 && (
        <Section title="Status History">
          <ol className="space-y-2">
            {lead.status_history.map((h, i) => (
              <li key={i} className="flex items-start gap-3 text-sm">
                <span className="text-gray-400 text-xs mt-0.5 w-32 flex-shrink-0">
                  {new Date(h.changed_at).toLocaleString()}
                </span>
                <Badge label={h.status} />
                {h.changed_by && <span className="text-gray-400 text-xs">by {h.changed_by}</span>}
                {h.notes && <span className="text-gray-500 text-xs">— {h.notes}</span>}
              </li>
            ))}
          </ol>
        </Section>
      )}
    </div>
  );
}

// ── Finalize form ─────────────────────────────────────────────────────────────

function FinalizeForm({ lead, onSuccess }: { lead: LeadDetail; onSuccess: () => void }) {
  const fd = lead.final_draft;
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");
  const [f, setF] = useState({
    final_subject: fd?.subject ?? lead.generated_draft?.subject ?? "",
    final_body: fd?.body ?? lead.generated_draft?.body ?? "",
    finalized_by: fd?.finalized_by ?? "",
    receiver_name: fd?.receiver?.receiver_name ?? "",
    receiver_role: fd?.receiver?.receiver_role ?? "",
    receiver_email: fd?.receiver?.receiver_email ?? "",
    linkedin_url: fd?.receiver?.linkedin_url ?? "",
    preferred_contact_method: fd?.receiver?.preferred_contact_method ?? "email",
    sender_name: fd?.sender?.sender_name ?? "",
    sender_role: fd?.sender?.sender_role ?? "",
    sender_company: fd?.sender?.sender_company ?? "",
    sender_email: fd?.sender?.sender_email ?? "",
    sender_phone: fd?.sender?.sender_phone ?? "",
    signature: fd?.sender?.signature ?? "",
  });

  function set(k: keyof typeof f, v: string) { setF((p) => ({ ...p, [k]: v })); }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!f.receiver_name || !f.receiver_email || !f.sender_name || !f.sender_email) {
      setErr("Receiver name/email and sender name/email are required.");
      return;
    }
    setErr(""); setSaving(true);
    try {
      await api.finalizeDraft(lead.lead_id, {
        final_subject: f.final_subject,
        final_body: f.final_body,
        finalized_by: f.finalized_by || undefined,
        receiver_details: {
          receiver_name: f.receiver_name,
          receiver_role: f.receiver_role || undefined,
          receiver_email: f.receiver_email,
          linkedin_url: f.linkedin_url || undefined,
          preferred_contact_method: f.preferred_contact_method,
        },
        sender_details: {
          sender_name: f.sender_name,
          sender_role: f.sender_role || undefined,
          sender_company: f.sender_company || undefined,
          sender_email: f.sender_email,
          sender_phone: f.sender_phone || undefined,
          signature: f.signature || undefined,
        },
      });
      onSuccess();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Section title="Finalize Draft">
      {err && <div className="mb-3"><ErrorMsg message={err} /></div>}
      <form onSubmit={submit} className="space-y-4">
        <div>
          <label className={lbl}>Subject</label>
          <input className={inp} value={f.final_subject} onChange={(e) => set("final_subject", e.target.value)} />
        </div>
        <div>
          <label className={lbl}>Message Body</label>
          <textarea className={inp} rows={6} value={f.final_body} onChange={(e) => set("final_body", e.target.value)} />
        </div>

        <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide pt-2">Receiver Details</p>
        <div className="grid grid-cols-2 gap-3">
          <F label="Name *"><input className={inp} value={f.receiver_name} onChange={(e) => set("receiver_name", e.target.value)} /></F>
          <F label="Role"><input className={inp} value={f.receiver_role} onChange={(e) => set("receiver_role", e.target.value)} /></F>
          <F label="Email *"><input className={inp} type="email" value={f.receiver_email} onChange={(e) => set("receiver_email", e.target.value)} /></F>
          <F label="LinkedIn URL"><input className={inp} value={f.linkedin_url} onChange={(e) => set("linkedin_url", e.target.value)} /></F>
          <F label="Preferred Contact">
            <select className={inp} value={f.preferred_contact_method} onChange={(e) => set("preferred_contact_method", e.target.value)}>
              {["email", "linkedin", "phone"].map((v) => <option key={v}>{v}</option>)}
            </select>
          </F>
        </div>

        <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide pt-2">Sender Details</p>
        <div className="grid grid-cols-2 gap-3">
          <F label="Name *"><input className={inp} value={f.sender_name} onChange={(e) => set("sender_name", e.target.value)} /></F>
          <F label="Role"><input className={inp} value={f.sender_role} onChange={(e) => set("sender_role", e.target.value)} /></F>
          <F label="Company"><input className={inp} value={f.sender_company} onChange={(e) => set("sender_company", e.target.value)} /></F>
          <F label="Email *"><input className={inp} type="email" value={f.sender_email} onChange={(e) => set("sender_email", e.target.value)} /></F>
          <F label="Phone"><input className={inp} value={f.sender_phone} onChange={(e) => set("sender_phone", e.target.value)} /></F>
          <F label="Finalized By"><input className={inp} value={f.finalized_by} onChange={(e) => set("finalized_by", e.target.value)} /></F>
        </div>
        <div>
          <label className={lbl}>Signature</label>
          <textarea className={inp} rows={3} value={f.signature} onChange={(e) => set("signature", e.target.value)} />
        </div>

        <button type="submit" disabled={saving} className="bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-sm font-medium px-5 py-2 rounded-md">
          {saving ? "Saving…" : "Finalize Draft → Mark Ready for Review"}
        </button>
      </form>
    </Section>
  );
}

// ── Status update ─────────────────────────────────────────────────────────────

const MANUAL_STATUSES = [
  "READY_FOR_REVIEW", "READY_TO_SEND", "CONTACTED",
  "REPLIED", "MEETING_SCHEDULED", "WON", "LOST", "ARCHIVED",
];

function StatusUpdateForm({ lead, onSuccess }: { lead: LeadDetail; onSuccess: () => void }) {
  const [status, setStatus] = useState(MANUAL_STATUSES[0]);
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(""); setSaving(true);
    try {
      await api.updateStatus(lead.lead_id, status, notes || undefined);
      setNotes("");
      onSuccess();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "Failed to update status");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Section title="Update Status">
      {err && <div className="mb-3"><ErrorMsg message={err} /></div>}
      <form onSubmit={submit} className="flex flex-wrap items-end gap-3">
        <div>
          <label className={lbl}>New Status</label>
          <select className={inp + " w-48"} value={status} onChange={(e) => setStatus(e.target.value)}>
            {MANUAL_STATUSES.map((s) => <option key={s}>{s}</option>)}
          </select>
        </div>
        <div className="flex-1 min-w-48">
          <label className={lbl}>Notes (optional)</label>
          <input className={inp} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="e.g. Sent intro email" />
        </div>
        <button type="submit" disabled={saving} className="bg-gray-800 hover:bg-gray-900 disabled:opacity-50 text-white text-sm font-medium px-4 py-2 rounded-md">
          {saving ? "Saving…" : "Update"}
        </button>
      </form>
    </Section>
  );
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Card>
      <h2 className="text-sm font-semibold text-gray-700 mb-3">{title}</h2>
      {children}
    </Card>
  );
}

function DL({ label, value }: { label: string; value: string | number | null | undefined }) {
  if (!value) return null;
  return (
    <div>
      <dt className="text-xs text-gray-400">{label}</dt>
      <dd className="text-gray-800">{value}</dd>
    </div>
  );
}

function F({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className={lbl}>{label}</label>
      {children}
    </div>
  );
}

const lbl = "block text-xs font-medium text-gray-600 mb-1";
const inp = "w-full border border-gray-300 rounded-md px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500";
