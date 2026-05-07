"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { ErrorMsg } from "@/components/ui/ErrorMsg";
import { Spinner } from "@/components/ui/Spinner";
import { Badge } from "@/components/ui/Badge";

type Account = { id: number; email_address: string; display_name: string; smtp_host: string; smtp_port: number; daily_limit: number; is_active: boolean };
type SentRecord = { lead_id: string; sender_email: string; receiver_email: string; subject: string; status: string; sent_at: string; error: string | null };
type JobStatus = { is_running: boolean; sent_today: number; sender_email: string | null; daily_limit: number | null };

export default function OutreachAgentPage() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [sentLog, setSentLog] = useState<SentRecord[]>([]);
  const [jobStatus, setJobStatus] = useState<JobStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showAddForm, setShowAddForm] = useState(false);
  const [interval, setIntervalMin] = useState(60);

  const [form, setForm] = useState({
    email_address: "", display_name: "", smtp_host: "",
    smtp_port: 587, smtp_username: "", smtp_password: "",
    use_tls: true, daily_limit: 50,
  });

  async function load() {
    try {
      const [accs, sent, status] = await Promise.all([
        api.getOutreachAccounts(),
        api.getOutreachSentLog(),
        api.getOutreachJobStatus(),
      ]);
      setAccounts((accs as { accounts: Account[] }).accounts);
      setSentLog((sent as { sent: SentRecord[] }).sent);
      setJobStatus(status as JobStatus);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  async function addAccount(e: React.FormEvent) {
    e.preventDefault();
    try {
      await api.addOutreachAccount(form);
      setShowAddForm(false);
      load();
    } catch (e: unknown) { setError(e instanceof Error ? e.message : "Failed"); }
  }

  async function startJob() {
    try { await api.startOutreachJob(interval); load(); }
    catch (e: unknown) { setError(e instanceof Error ? e.message : "Failed"); }
  }

  async function stopJob() {
    try { await api.stopOutreachJob(); load(); }
    catch (e: unknown) { setError(e instanceof Error ? e.message : "Failed"); }
  }

  async function runNow() {
    try { const r = await api.runOutreachNow(); alert(`Sent: ${(r as { sent: number }).sent}`); load(); }
    catch (e: unknown) { setError(e instanceof Error ? e.message : "Failed"); }
  }

  if (loading) return <Spinner />;

  return (
    <div className="max-w-4xl space-y-6">
      <h1 className="text-lg font-semibold">Outreach Agent</h1>
      {error && <ErrorMsg message={error} />}

      {/* Job Status */}
      <div className="bg-white border border-gray-200 rounded-lg p-5">
        <h2 className="text-sm font-semibold text-gray-700 mb-3">Job Status</h2>
        {jobStatus && (
          <div className="flex items-center gap-6 text-sm">
            <div className="flex items-center gap-2">
              <span className={`w-2 h-2 rounded-full ${jobStatus.is_running ? "bg-green-500 animate-pulse" : "bg-gray-300"}`} />
              <span>{jobStatus.is_running ? "Running" : "Stopped"}</span>
            </div>
            {jobStatus.sender_email && <span className="text-gray-500">From: {jobStatus.sender_email}</span>}
            <span className="text-gray-500">Sent today: <strong>{jobStatus.sent_today}</strong>{jobStatus.daily_limit ? ` / ${jobStatus.daily_limit}` : ""}</span>
          </div>
        )}
        <div className="flex items-center gap-3 mt-4">
          {!jobStatus?.is_running ? (
            <>
              <div className="flex items-center gap-2">
                <label className="text-xs text-gray-500">Interval (min):</label>
                <input type="number" min={15} value={interval} onChange={(e) => setIntervalMin(parseInt(e.target.value) || 60)}
                  className="border border-gray-300 rounded px-2 py-1 text-sm w-20" />
              </div>
              <button onClick={startJob} className="bg-green-600 hover:bg-green-700 text-white text-sm font-medium px-4 py-2 rounded-md">
                Start Job
              </button>
            </>
          ) : (
            <button onClick={stopJob} className="bg-red-600 hover:bg-red-700 text-white text-sm font-medium px-4 py-2 rounded-md">
              Stop Job
            </button>
          )}
          <button onClick={runNow} className="bg-gray-800 hover:bg-gray-900 text-white text-sm font-medium px-4 py-2 rounded-md">
            Run Now (1 cycle)
          </button>
        </div>
      </div>

      {/* Sender Accounts */}
      <div className="bg-white border border-gray-200 rounded-lg p-5">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-gray-700">Sender Email Accounts</h2>
          <button onClick={() => setShowAddForm(!showAddForm)} className="text-xs text-blue-600 hover:underline">
            {showAddForm ? "Cancel" : "+ Add Account"}
          </button>
        </div>

        {showAddForm && (
          <form onSubmit={addAccount} className="border border-gray-200 rounded-md p-4 mb-4 space-y-3 bg-gray-50">
            <div className="grid grid-cols-2 gap-3">
              {[
                ["Email Address", "email_address", "email"],
                ["Display Name", "display_name", "text"],
                ["SMTP Host", "smtp_host", "text"],
                ["SMTP Port", "smtp_port", "number"],
                ["SMTP Username", "smtp_username", "text"],
                ["SMTP Password", "smtp_password", "password"],
                ["Daily Limit", "daily_limit", "number"],
              ].map(([label, key, type]) => (
                <div key={key}>
                  <label className="block text-xs font-medium text-gray-600 mb-1">{label}</label>
                  <input type={type} required={["email_address","smtp_host","smtp_username","smtp_password"].includes(key)}
                    className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm"
                    value={(form as Record<string, unknown>)[key] as string}
                    onChange={(e) => setForm((f) => ({ ...f, [key]: type === "number" ? parseInt(e.target.value) : e.target.value }))} />
                </div>
              ))}
            </div>
            <button type="submit" className="bg-blue-600 text-white text-sm px-4 py-2 rounded-md">Add Account</button>
          </form>
        )}

        {accounts.length === 0 ? (
          <p className="text-sm text-gray-400">No sender accounts yet. Add one to start sending.</p>
        ) : (
          <div className="space-y-2">
            {accounts.map((a) => (
              <div key={a.id} className="flex items-center justify-between text-sm border border-gray-100 rounded p-2">
                <div>
                  <span className="font-medium">{a.email_address}</span>
                  {a.display_name && <span className="text-gray-400 ml-2">({a.display_name})</span>}
                  <span className="text-gray-400 ml-2 text-xs">{a.smtp_host}:{a.smtp_port}</span>
                </div>
                <span className="text-xs text-gray-400">Limit: {a.daily_limit}/day</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Sent Log */}
      <div className="bg-white border border-gray-200 rounded-lg p-5">
        <h2 className="text-sm font-semibold text-gray-700 mb-3">Sent Log ({sentLog.length})</h2>
        {sentLog.length === 0 ? (
          <p className="text-sm text-gray-400">No emails sent yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs border-collapse">
              <thead>
                <tr className="border-b border-gray-200 text-left text-gray-500">
                  <th className="pb-2 pr-3">To</th>
                  <th className="pb-2 pr-3">Subject</th>
                  <th className="pb-2 pr-3">Status</th>
                  <th className="pb-2">Sent At</th>
                </tr>
              </thead>
              <tbody>
                {sentLog.map((r, i) => (
                  <tr key={i} className="border-b border-gray-50">
                    <td className="py-1.5 pr-3 text-gray-700">{r.receiver_email}</td>
                    <td className="py-1.5 pr-3 text-gray-600 max-w-xs truncate">{r.subject}</td>
                    <td className="py-1.5 pr-3"><Badge label={r.status.toUpperCase()} /></td>
                    <td className="py-1.5 text-gray-400">{new Date(r.sent_at).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
