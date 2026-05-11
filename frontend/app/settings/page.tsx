"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { ErrorMsg } from "@/components/ui/ErrorMsg";
import { Spinner } from "@/components/ui/Spinner";

type Settings = {
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
const MODES = ["semi-autonomous", "manual"];

export default function SettingsPage() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api.getSettings()
      .then((r) => setSettings(r as Settings))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

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

      {/* Outreach Settings — stub */}
      <Section title="Email & Outreach Settings">
        <p className="text-sm text-gray-400 italic">
          Outreach Agent coming soon. Settings are saved and will be applied when the agent is built.
        </p>
        <div className="space-y-4 mt-3 opacity-60 pointer-events-none">
          <div className="grid grid-cols-2 gap-4">
            <Field label="Sender Domain"><input className={inp} value={settings.outreach.sender_domain ?? ""} readOnly /></Field>
            <Field label="Daily Send Limit"><input type="number" className={inp} value={settings.outreach.daily_send_limit} readOnly /></Field>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <Field label="Send Window Start (UTC)"><input className={inp} value={settings.outreach.send_window_start} readOnly /></Field>
            <Field label="Send Window End (UTC)"><input className={inp} value={settings.outreach.send_window_end} readOnly /></Field>
          </div>
        </div>
      </Section>

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
