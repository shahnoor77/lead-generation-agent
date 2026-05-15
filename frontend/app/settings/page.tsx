"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { ErrorMsg } from "@/components/ui/ErrorMsg";
import { Spinner } from "@/components/ui/Spinner";

/** Persisted outbound sender identity (GET /outreach/account) — never contains raw passwords */
type PersistedSenderAccount = {
  configured: boolean;
  id?: number;
  email_address?: string;
  display_name?: string;
  smtp_host?: string;
  smtp_port?: number;
  smtp_username?: string;
  smtp_password_configured?: boolean;
  use_tls?: boolean;
  daily_limit?: number;
  imap_host?: string | null;
  imap_port?: number;
  imap_username?: string | null;
  imap_password_configured?: boolean;
  imap_use_ssl?: boolean;
  is_active?: boolean;
};

function pruneEmptyPasswordFields<T extends Record<string, unknown>>(p: T): T {
  const out = { ...p };
  if (!String(out.smtp_password ?? "").trim()) delete out.smtp_password;
  if (!String(out.imap_password ?? "").trim()) delete out.imap_password;
  return out;
}

const SHOW_SANDBOX_UI = process.env.NEXT_PUBLIC_ENABLE_SANDBOX_UI !== "false";

type Settings = {
  sandbox_outreach_available?: boolean;
  icp: {
    decision_maker_titles: string[];
    target_industries: string[];
    ownership_types: string[];
    revenue_min: number | null;
    revenue_max: number | null;
    growth_stage: string | null;
    primary_geography: string | null;
    min_fit_score: number;
    require_website: boolean;
    require_contact: boolean;
  };
  outreach: {
    sender_domain: string | null;
    daily_send_limit: number;
    send_window_start: string;
    send_window_end: string;
    language_default: string;
  };
  ai_agent: {
    model: string;
    agent_mode: string;
    email_tone: string;
    hypothesis_depth: string;
    summary_depth: string;
  };
};

const TONES = ["executive-direct", "formal-business", "problem-specific"];
const DEPTHS = ["concise", "standard", "detailed"];

export default function SettingsPage() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [senderPersisted, setSenderPersisted] = useState<PersistedSenderAccount | null>(null);
  const [senderEditing, setSenderEditing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [savingSender, setSavingSender] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [sandboxEmailsInput, setSandboxEmailsInput] = useState("");
  const [sandboxRows, setSandboxRows] = useState<{ id: number; email: string }[]>([]);
  const [sandboxBusy, setSandboxBusy] = useState(false);
  const [senderForm, setSenderForm] = useState({
    email_address: "",
    display_name: "",
    smtp_host: "",
    smtp_port: 587,
    smtp_username: "",
    smtp_password: "",
    use_tls: true,
    daily_limit: 50,
    imap_host: "",
    imap_port: 993,
    imap_username: "",
    imap_password: "",
    imap_use_ssl: true,
  });

  function applyPersistedIntoForm(p: PersistedSenderAccount | null, clearPasswords = false) {
    if (!p || !p.configured) return;
    setSenderForm((f) => ({
      ...f,
      email_address: p.email_address || "",
      display_name: p.display_name || "",
      smtp_host: p.smtp_host || "",
      smtp_port: p.smtp_port ?? 587,
      smtp_username: p.smtp_username || "",
      smtp_password: clearPasswords ? "" : f.smtp_password,
      use_tls: p.use_tls !== false,
      daily_limit: p.daily_limit ?? 50,
      imap_host: p.imap_host || "",
      imap_port: p.imap_port ?? 993,
      imap_username: p.imap_username || "",
      imap_password: clearPasswords ? "" : f.imap_password,
      imap_use_ssl: p.imap_use_ssl !== false,
    }));
  }

  useEffect(() => {
    Promise.all([api.getSettings(), api.getOutreachAccount()])
      .then(([s, acc]) => {
        const sess = s as Settings;
        setSettings(sess);

        const p = acc as PersistedSenderAccount;
        if (p?.configured) {
          setSenderPersisted(p);
          applyPersistedIntoForm(p, true);
          setSenderEditing(false);
        } else {
          setSenderPersisted(null);
          setSenderEditing(true);
        }

        if (SHOW_SANDBOX_UI && sess.sandbox_outreach_available !== false) {
          api
            .listSandboxInboxes()
            .then((r) =>
              setSandboxRows((r.inboxes ?? []).map((x) => ({ id: x.id, email: x.email })))
            )
            .catch(() => setSandboxRows([]));
        }
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  async function reloadSandboxInboxes() {
    if (!SHOW_SANDBOX_UI) return;
    try {
      const r = await api.listSandboxInboxes();
      setSandboxRows((r.inboxes ?? []).map((x) => ({ id: x.id, email: x.email })));
    } catch {
      setSandboxRows([]);
    }
  }

  async function saveSandboxInboxes() {
    setSandboxBusy(true);
    setError("");
    try {
      const parts = sandboxEmailsInput.split(/[\n,;\s]+/).map((x) => x.trim().toLowerCase()).filter(Boolean);
      await api.replaceSandboxInboxes(parts);
      setSandboxEmailsInput("");
      await reloadSandboxInboxes();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to save sandbox inboxes");
    } finally {
      setSandboxBusy(false);
    }
  }

  async function clearSandboxMappings() {
    if (!confirm("Clear all lead→sandbox assignments? Next sandbox sends may pick inboxes anew.")) return;
    setSandboxBusy(true);
    setError("");
    try {
      await api.clearSandboxLeadMap();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to clear mappings");
    } finally {
      setSandboxBusy(false);
    }
  }

  async function removeSandboxRow(id: number) {
    setSandboxBusy(true);
    setError("");
    try {
      await api.deleteSandboxInboxRow(id);
      await reloadSandboxInboxes();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to delete row");
    } finally {
      setSandboxBusy(false);
    }
  }

  async function save() {
    if (!settings) return;
    setSaving(true); setError(""); setSaved(false);
    try {
      await api.saveSettings(settings);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  function setICP<K extends keyof Settings["icp"]>(k: K, v: Settings["icp"][K]) {
    setSettings((s) => s ? { ...s, icp: { ...s.icp, [k]: v } } : s);
  }
  function setAI<K extends keyof Settings["ai_agent"]>(k: K, v: Settings["ai_agent"][K]) {
    setSettings((s) => s ? { ...s, ai_agent: { ...s.ai_agent, [k]: v } } : s);
  }
  function setSender<K extends keyof typeof senderForm>(k: K, v: (typeof senderForm)[K]) {
    setSenderForm((f) => ({ ...f, [k]: v }));
  }
  async function savePersistedSender() {
    const firstSetup = senderPersisted == null;
    if (!senderForm.email_address || !senderForm.smtp_host || !senderForm.smtp_username) {
      setError("Sender email, SMTP host, and SMTP username are required.");
      return;
    }
    if (firstSetup && !senderForm.smtp_password.trim()) {
      setError("SMTP password is required the first time you configure the sender.");
      return;
    }
    setSavingSender(true);
    setError("");
    try {
      const body = pruneEmptyPasswordFields({
        email_address: senderForm.email_address,
        display_name: senderForm.display_name,
        smtp_host: senderForm.smtp_host,
        smtp_port: senderForm.smtp_port,
        smtp_username: senderForm.smtp_username,
        smtp_password: senderForm.smtp_password.trim() ? senderForm.smtp_password : undefined,
        use_tls: senderForm.use_tls,
        daily_limit: senderForm.daily_limit,
        imap_host: senderForm.imap_host || undefined,
        imap_port: senderForm.imap_port,
        imap_username: senderForm.imap_username || undefined,
        imap_password: senderForm.imap_password.trim() ? senderForm.imap_password : undefined,
        imap_use_ssl: senderForm.imap_use_ssl,
      }) as Record<string, unknown>;

      const updated = await api.saveOutreachAccount(body);
      const p = updated as PersistedSenderAccount;
      setSenderPersisted({
        configured: true,
        ...p,
      });
      setSenderEditing(false);
      applyPersistedIntoForm({ configured: true, ...p }, true);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to save sender account");
    } finally {
      setSavingSender(false);
    }
  }

  async function deactivatePrimarySender() {
    if (!senderPersisted?.id) return;
    try {
      await api.removeOutreachAccount(senderPersisted.id);
      setSenderPersisted(null);
      setSenderEditing(true);
      setSenderForm((f) => ({
        ...f,
        email_address: "",
        display_name: "",
        smtp_host: "",
        smtp_username: "",
        smtp_password: "",
        imap_host: "",
        imap_username: "",
        imap_password: "",
      }));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to disconnect sender");
    }
  }

  if (loading) return <Spinner />;
  if (!settings) return <ErrorMsg message={error || "Failed to load settings"} />;

  return (
    <div className="max-w-3xl space-y-8">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Settings</h1>
        <div className="flex items-center gap-3">
          {saved && <span className="text-sm text-green-600">Saved ✓</span>}
          {error && <span className="text-sm text-red-600">{error}</span>}
          <button onClick={save} disabled={saving}
            className="bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-sm font-medium px-4 py-2 rounded-md">
            {saving ? "Saving…" : "Save Settings"}
          </button>
        </div>
      </div>

      {/* ICP Settings */}
      <Section title="Ideal Customer Profile (ICP)">
        <div className="space-y-4">
          <Field label="Decision Maker Titles" hint="Comma-separated">
            <input className={inp} value={settings.icp.decision_maker_titles.join(", ")}
              onChange={(e) => setICP("decision_maker_titles", e.target.value.split(",").map(s => s.trim()).filter(Boolean))} />
          </Field>
          <Field label="Target Industries" hint="Comma-separated">
            <input className={inp} value={settings.icp.target_industries.join(", ")}
              onChange={(e) => setICP("target_industries", e.target.value.split(",").map(s => s.trim()).filter(Boolean))} />
          </Field>
          <Field label="Ownership Types" hint="Comma-separated">
            <input className={inp} value={settings.icp.ownership_types.join(", ")}
              onChange={(e) => setICP("ownership_types", e.target.value.split(",").map(s => s.trim()).filter(Boolean))} />
          </Field>
          <div className="grid grid-cols-2 gap-4">
            <Field label="Revenue Min (USD)">
              <input type="number" className={inp} value={settings.icp.revenue_min ?? ""}
                onChange={(e) => setICP("revenue_min", e.target.value ? parseInt(e.target.value) : null)} placeholder="e.g. 1000000" />
            </Field>
            <Field label="Revenue Max (USD)">
              <input type="number" className={inp} value={settings.icp.revenue_max ?? ""}
                onChange={(e) => setICP("revenue_max", e.target.value ? parseInt(e.target.value) : null)} placeholder="e.g. 200000000" />
            </Field>
          </div>
          <Field label="Growth Stage">
            <input className={inp} value={settings.icp.growth_stage ?? ""}
              onChange={(e) => setICP("growth_stage", e.target.value || null)} placeholder="e.g. Scaling up to $200M" />
          </Field>
          <Field label="Primary Geography">
            <input className={inp} value={settings.icp.primary_geography ?? ""}
              onChange={(e) => setICP("primary_geography", e.target.value || null)} placeholder="e.g. Saudi Arabia, UAE, Pakistan" />
          </Field>
          <Field label={`Minimum Fit Score: ${settings.icp.min_fit_score}`} hint="Leads below this score are rejected (0–100)">
            <input type="range" min={0} max={100} step={5} className="w-full"
              value={settings.icp.min_fit_score}
              onChange={(e) => setICP("min_fit_score", parseInt(e.target.value))} />
            <div className="flex justify-between text-xs text-gray-400 mt-1"><span>0</span><span>50</span><span>100</span></div>
          </Field>
          <div className="flex gap-6">
            <Toggle label="Require Website" checked={settings.icp.require_website}
              onChange={(v) => setICP("require_website", v)} />
            <Toggle label="Require Contact Info" checked={settings.icp.require_contact}
              onChange={(v) => setICP("require_contact", v)} />
          </div>
        </div>
      </Section>

      {/* Outreach Settings */}
      <Section title="Email & Outreach Settings">
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <Field label="Sender Domain">
              <input
                className={inp}
                value={settings.outreach.sender_domain ?? ""}
                onChange={(e) => setSettings((s) => s ? { ...s, outreach: { ...s.outreach, sender_domain: e.target.value || null } } : s)}
                placeholder="e.g. yourcompany.com"
              />
            </Field>
            <Field label="Daily Send Limit">
              <input
                type="number"
                className={inp}
                value={settings.outreach.daily_send_limit}
                onChange={(e) => setSettings((s) => s ? { ...s, outreach: { ...s.outreach, daily_send_limit: parseInt(e.target.value || "50") } } : s)}
              />
            </Field>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <Field label="Send Window Start (UTC)">
              <input
                className={inp}
                value={settings.outreach.send_window_start}
                onChange={(e) => setSettings((s) => s ? { ...s, outreach: { ...s.outreach, send_window_start: e.target.value } } : s)}
              />
            </Field>
            <Field label="Send Window End (UTC)">
              <input
                className={inp}
                value={settings.outreach.send_window_end}
                onChange={(e) => setSettings((s) => s ? { ...s, outreach: { ...s.outreach, send_window_end: e.target.value } } : s)}
              />
            </Field>
          </div>
          <Field label="Default Language">
            <input
              className={inp}
              value={settings.outreach.language_default}
              onChange={(e) => setSettings((s) => s ? { ...s, outreach: { ...s.outreach, language_default: e.target.value } } : s)}
              placeholder="EN | AR | AUTO"
            />
          </Field>
        </div>
      </Section>

      <Section title="Sender Email (SMTP & IMAP)">
        <div className="space-y-4">
          {!senderEditing && senderPersisted && (
            <div className="border border-emerald-200 bg-emerald-50 rounded-lg p-4 space-y-2">
              <div className="flex items-start justify-between gap-3 flex-wrap">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-emerald-800">
                    Stored for your account · used for all outbound mail & inbox reply checks
                  </p>
                  <p className="text-sm font-semibold text-gray-900 mt-1">
                    {senderPersisted.email_address}
                    {senderPersisted.display_name ? ` · ${senderPersisted.display_name}` : ""}
                  </p>
                  <dl className="mt-3 grid gap-1 text-xs text-gray-700 sm:grid-cols-2">
                    <div><span className="text-gray-500">SMTP</span> {senderPersisted.smtp_username} @ {senderPersisted.smtp_host}:{senderPersisted.smtp_port} · TLS {senderPersisted.use_tls ? "on" : "off"} · password {senderPersisted.smtp_password_configured ? "saved" : "missing"}</div>
                    <div><span className="text-gray-500">IMAP</span> {(senderPersisted.imap_host || "(auto)")} · port {senderPersisted.imap_port} · user {senderPersisted.imap_username || senderPersisted.email_address}{" "}· SSL {senderPersisted.imap_use_ssl ? "on" : "off"} · password {senderPersisted.imap_password_configured ? "saved" : "uses SMTP"}</div>
                  </dl>
                  <p className="text-xs text-gray-500 mt-2">Daily cap: {senderPersisted.daily_limit} sends/day (also respects outreach settings).</p>
                </div>
                <div className="flex gap-2 flex-shrink-0">
                  <button
                    type="button"
                    onClick={() => {
                      applyPersistedIntoForm(senderPersisted, true);
                      setSenderEditing(true);
                    }}
                    className="text-sm px-3 py-1.5 rounded-md border border-gray-300 bg-white hover:bg-gray-50 text-gray-800"
                  >
                    Edit
                  </button>
                  <button
                    type="button"
                    onClick={() => deactivatePrimarySender()}
                    className="text-sm px-3 py-1.5 rounded-md border border-red-200 text-red-700 hover:bg-red-50"
                  >
                    Disconnect
                  </button>
                </div>
              </div>
            </div>
          )}

          {(senderEditing || !senderPersisted) && (
            <>
              {!senderPersisted ? (
                <p className="text-sm text-gray-600">
                  Enter your SMTP (required) and IMAP (recommended for replies) credentials once—they stay saved until you change or disconnect them.
                </p>
              ) : (
                <div className="flex items-center gap-3">
                  <span className="text-sm font-medium text-gray-700">Editing sender</span>
                  <button type="button" className="text-xs text-blue-700 hover:underline" onClick={() => { setSenderEditing(false); applyPersistedIntoForm(senderPersisted, true); }}>
                    Cancel
                  </button>
                </div>
              )}
              <div className="grid grid-cols-2 gap-4">
                <Field label="Sender Email *"><input className={inp} value={senderForm.email_address} onChange={(e) => setSender("email_address", e.target.value)} /></Field>
                <Field label="Display Name"><input className={inp} value={senderForm.display_name} onChange={(e) => setSender("display_name", e.target.value)} /></Field>
                <Field label="SMTP Host *"><input className={inp} value={senderForm.smtp_host} onChange={(e) => setSender("smtp_host", e.target.value)} /></Field>
                <Field label="SMTP Port"><input type="number" className={inp} value={senderForm.smtp_port} onChange={(e) => setSender("smtp_port", parseInt(e.target.value || "587", 10))} /></Field>
                <Field label="SMTP Username *"><input className={inp} value={senderForm.smtp_username} onChange={(e) => setSender("smtp_username", e.target.value)} /></Field>
                <Field label={senderPersisted?.smtp_password_configured ? "SMTP Password (leave blank to keep)" : "SMTP Password *"} hint={senderPersisted?.smtp_password_configured ? "" : undefined}>
                  <input type="password" className={inp} value={senderForm.smtp_password} onChange={(e) => setSender("smtp_password", e.target.value)} />
                </Field>
                <Field label="Daily Limit"><input type="number" className={inp} value={senderForm.daily_limit} onChange={(e) => setSender("daily_limit", parseInt(e.target.value || "50", 10))} /></Field>
                <Field label="IMAP Host (optional)" hint='Leave empty to derive from SMTP (e.g. smtp.host → imap.host)'><input className={inp} value={senderForm.imap_host} onChange={(e) => setSender("imap_host", e.target.value)} /></Field>
                <Field label="IMAP Port"><input type="number" className={inp} value={senderForm.imap_port} onChange={(e) => setSender("imap_port", parseInt(e.target.value || "993", 10))} /></Field>
                <Field label="IMAP Username"><input className={inp} value={senderForm.imap_username} onChange={(e) => setSender("imap_username", e.target.value)} /></Field>
                <Field label={senderPersisted?.imap_password_configured ? "IMAP Password (leave blank to keep)" : "IMAP Password (optional)"}>
                  <input type="password" className={inp} value={senderForm.imap_password} onChange={(e) => setSender("imap_password", e.target.value)} />
                </Field>
              </div>
              <div className="flex gap-6">
                <Toggle label="Use TLS (SMTP)" checked={senderForm.use_tls} onChange={(v) => setSender("use_tls", v)} />
                <Toggle label="Use SSL (IMAP)" checked={senderForm.imap_use_ssl} onChange={(v) => setSender("imap_use_ssl", v)} />
              </div>
              <button
                onClick={() => savePersistedSender()}
                disabled={savingSender}
                className="bg-gray-800 hover:bg-gray-900 disabled:opacity-50 text-white text-sm font-medium px-4 py-2 rounded-md"
              >
                {savingSender ? "Saving…" : senderPersisted ? "Save Changes" : "Save Sender"}
              </button>
            </>
          )}
        </div>
      </Section>

      {SHOW_SANDBOX_UI && settings.sandbox_outreach_available !== false && (
        <Section title="Sandbox test inboxes">
          <p className="text-xs text-gray-500 mb-3">
            When you start a pipeline with <strong>Test (sandbox)</strong>, outbound mail is routed to these addresses
            instead of real leads. Hide this section in production with{" "}
            <code className="text-[11px] bg-gray-100 px-1 rounded">SANDBOX_OUTREACH_ENABLED=false</code>{" "}
            and <code className="text-[11px] bg-gray-100 px-1 rounded">NEXT_PUBLIC_ENABLE_SANDBOX_UI=false</code>.
          </p>
          <textarea
            className={inp}
            rows={3}
            placeholder="comma or newline-separated test addresses…"
            value={sandboxEmailsInput}
            disabled={sandboxBusy}
            onChange={(e) => setSandboxEmailsInput(e.target.value)}
          />
          <div className="flex flex-wrap gap-2 mt-2">
            <button
              type="button"
              disabled={sandboxBusy}
              className="px-3 py-1.5 text-sm rounded-md bg-amber-600 text-white hover:bg-amber-700 disabled:opacity-50"
              onClick={() => void saveSandboxInboxes()}
            >
              Replace list from text above
            </button>
            <button
              type="button"
              disabled={sandboxBusy}
              className="px-3 py-1.5 text-sm rounded-md border border-gray-300 text-gray-700 hover:bg-gray-50 disabled:opacity-50"
              onClick={() => void clearSandboxMappings()}
            >
              Clear lead→sandbox map
            </button>
          </div>
          {sandboxRows.length > 0 && (
            <ul className="mt-4 text-sm text-gray-700 space-y-1">
              {sandboxRows.map((r) => (
                <li key={r.id} className="flex items-center justify-between gap-2 border-b border-gray-100 py-1">
                  <span className="font-mono text-xs">{r.email}</span>
                  <button
                    type="button"
                    className="text-xs text-red-600 hover:underline disabled:opacity-50"
                    disabled={sandboxBusy}
                    onClick={() => void removeSandboxRow(r.id)}
                  >
                    Remove
                  </button>
                </li>
              ))}
            </ul>
          )}
          {sandboxRows.length === 0 && !sandboxBusy && (
            <p className="text-xs text-amber-700 mt-2">No sandbox inboxes saved yet.</p>
          )}
        </Section>
      )}

      {/* AI Agent Settings */}
      <Section title="AI Agent Settings">
        <div className="space-y-4">
          <Field label="LLM Model" hint="Ollama model name">
            <input className={inp} value={settings.ai_agent.model}
              onChange={(e) => setAI("model", e.target.value)} placeholder="qwen2.5-coder:14b" />
          </Field>

          {/* Workflow Mode — visual card selector */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Workflow Mode</label>
            <div className="grid grid-cols-2 gap-3">
              {[
                {
                  value: "semi-autonomous",
                  title: "Semi-Autonomous",
                  icon: "✋",
                  description: "Pipeline stops after draft generation. You review and edit each email, manually approve, then trigger send per industry.",
                  badge: "Human in the loop",
                  badgeColor: "bg-yellow-100 text-yellow-700",
                },
                {
                  value: "autonomous",
                  title: "Autonomous",
                  icon: "⚡",
                  description: "Pipeline runs end-to-end. Emails are generated with higher precision settings, auto-approved, and sent immediately.",
                  badge: "Fully automated",
                  badgeColor: "bg-green-100 text-green-700",
                },
              ].map((mode) => (
                <button
                  key={mode.value}
                  type="button"
                  onClick={() => setAI("agent_mode", mode.value)}
                  className={`text-left p-4 rounded-lg border-2 transition-colors ${
                    settings.ai_agent.agent_mode === mode.value
                      ? "border-blue-500 bg-blue-50"
                      : "border-gray-200 hover:border-gray-300 bg-white"
                  }`}
                >
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-lg">{mode.icon}</span>
                    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${mode.badgeColor}`}>
                      {mode.badge}
                    </span>
                  </div>
                  <p className="text-sm font-semibold text-gray-900">{mode.title}</p>
                  <p className="text-xs text-gray-500 mt-1 leading-relaxed">{mode.description}</p>
                </button>
              ))}
            </div>
          </div>

          <Field label="Email Tone">
            <select className={inp} value={settings.ai_agent.email_tone}
              onChange={(e) => setAI("email_tone", e.target.value)}>
              {TONES.map((t) => <option key={t} value={t}>{t.replace(/-/g, " ")}</option>)}
            </select>
          </Field>
          <div className="grid grid-cols-2 gap-4">
            <Field label="Hypothesis Depth" hint="How detailed pain point inferences are">
              <select className={inp} value={settings.ai_agent.hypothesis_depth}
                onChange={(e) => setAI("hypothesis_depth", e.target.value)}>
                {DEPTHS.map((d) => <option key={d} value={d}>{d}</option>)}
              </select>
            </Field>
            <Field label="Summary Depth" hint="How detailed company summaries are">
              <select className={inp} value={settings.ai_agent.summary_depth}
                onChange={(e) => setAI("summary_depth", e.target.value)}>
                {DEPTHS.map((d) => <option key={d} value={d}>{d}</option>)}
              </select>
            </Field>
          </div>
        </div>
      </Section>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-white border border-gray-200 rounded-lg p-5">
      <h2 className="text-sm font-semibold text-gray-700 mb-4">{title}</h2>
      {children}
    </div>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-1">{label}</label>
      {hint && <p className="text-xs text-gray-400 mb-1">{hint}</p>}
      {children}
    </div>
  );
}

function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <div className="flex items-center gap-2">
      <button type="button" onClick={() => onChange(!checked)}
        className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${checked ? "bg-blue-600" : "bg-gray-300"}`}>
        <span className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${checked ? "translate-x-4" : "translate-x-0.5"}`} />
      </button>
      <span className="text-sm text-gray-700">{label}</span>
    </div>
  );
}

const inp = "w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500";
