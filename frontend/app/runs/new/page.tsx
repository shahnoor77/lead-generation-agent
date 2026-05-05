"use client";
import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { ErrorMsg } from "@/components/ui/ErrorMsg";

const LANG_OPTIONS = ["EN", "AR", "AUTO"];

type State = "idle" | "submitting" | "processing" | "error";

export default function NewRunPage() {
  const router = useRouter();
  const [state, setState] = useState<State>("idle");
  const [error, setError] = useState("");
  const [runId, setRunId] = useState("");

  const [form, setForm] = useState({
    industries: "",
    domain: "",
    location: "",
    country: "",
    excluded_categories: "",
    our_services: "",
    target_pain_patterns: "",
    pain_points: "",
    value_proposition: "",
    notes: "",
    language_preference: "EN",
    continuous: false,
    continuous_interval_minutes: 60,
  });

  useEffect(() => {
    // Restore last-saved config for this user
    api.getSavedConfig().then((res) => {
      if (!res.config) return;
      const c = res.config as Record<string, unknown>;
      setForm((f) => ({
        ...f,
        industries: Array.isArray(c.industries) ? (c.industries as string[]).join(", ") : f.industries,
        domain: (c.domain as string) || f.domain,
        location: (c.location as string) || f.location,
        country: (c.country as string) || f.country,
        excluded_categories: Array.isArray(c.excluded_categories) ? (c.excluded_categories as string[]).join(", ") : f.excluded_categories,
        our_services: Array.isArray(c.our_services) ? (c.our_services as string[]).join(", ") : f.our_services,
        target_pain_patterns: Array.isArray(c.target_pain_patterns) ? (c.target_pain_patterns as string[]).join(", ") : f.target_pain_patterns,
        pain_points: Array.isArray(c.pain_points) ? (c.pain_points as string[]).join(", ") : f.pain_points,
        value_proposition: (c.value_proposition as string) || f.value_proposition,
        notes: (c.notes as string) || f.notes,
        language_preference: (c.language_preference as string) || f.language_preference,
        continuous: (c.continuous as boolean) ?? f.continuous,
        continuous_interval_minutes: (c.continuous_interval_minutes as number) || f.continuous_interval_minutes,
      }));
    }).catch(() => {});
  }, []);

  function set(k: keyof typeof form, v: string) {
    setForm((f) => ({ ...f, [k]: v }));
  }

  function splitCSV(s: string) {
    return s.split(",").map((x) => x.trim()).filter(Boolean);
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.industries.trim() || !form.location.trim()) {
      setError("Industries and Location are required.");
      return;
    }
    setError("");
    setState("submitting");

    try {
      const res = await api.startRun({
        context: {
          industries: splitCSV(form.industries),
          location: form.location,
          country: form.country || undefined,
          domain: form.domain || undefined,
          excluded_categories: splitCSV(form.excluded_categories),
          our_services: splitCSV(form.our_services),
          target_pain_patterns: splitCSV(form.target_pain_patterns),
          pain_points: splitCSV(form.pain_points),
          value_proposition: form.value_proposition || undefined,
          notes: form.notes || undefined,
          language_preference: form.language_preference,
          continuous: form.continuous,
          continuous_interval_minutes: form.continuous_interval_minutes,
        },
      });

      setRunId(res.pipeline_run_id);
      setState("processing");

      // Wait 4 seconds so the pipeline run record is saved to DB, then go to runs list
      setTimeout(() => router.push("/runs"), 4000);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to start run");
      setState("error");
    }
  }

  // ── Processing state ───────────────────────────────────────────────────────
  if (state === "processing") {
    return (
      <div className="max-w-md mx-auto mt-20 text-center space-y-6">
        <div className="flex justify-center">
          <div className="w-12 h-12 border-4 border-gray-200 border-t-blue-600 rounded-full animate-spin" />
        </div>
        <div>
          <h2 className="text-lg font-semibold text-gray-900">Pipeline Started</h2>
          <p className="text-sm text-gray-500 mt-1">
            Discovering and enriching leads for{" "}
            <strong>{form.industries}</strong> in{" "}
            <strong>{form.location}{form.country ? `, ${form.country}` : ""}</strong>.
          </p>
          <p className="text-xs text-gray-400 mt-3">
            Run ID: <code className="bg-gray-100 px-1 rounded">{runId}</code>
          </p>
        </div>
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 text-sm text-blue-700 space-y-1">
          <p className="font-medium">This may take a few minutes.</p>
          <p>Redirecting to Runs dashboard…</p>
        </div>
        <p className="text-xs text-gray-400">
          You can track progress from the Runs dashboard once redirected.
        </p>
      </div>
    );
  }

  // ── Form state ─────────────────────────────────────────────────────────────
  return (
    <div className="max-w-2xl">
      <h1 className="text-lg font-semibold mb-6">New Lead Generation Run</h1>

      {state === "error" && error && (
        <div className="mb-4"><ErrorMsg message={error} /></div>
      )}

      <form onSubmit={submit} className="space-y-4">
        <Field label="Industries *" hint="Comma-separated, e.g. manufacturing, logistics">
          <input
            className={input}
            value={form.industries}
            onChange={(e) => set("industries", e.target.value)}
            placeholder="manufacturing, logistics"
          />
        </Field>

        <Field label="Domain" hint="Sub-sector of TARGET companies — what THEY do (e.g. 'automobile parts', 'cold chain', 'FMCG'). NOT your services.">
          <input
            className={input}
            value={form.domain}
            onChange={(e) => set("domain", e.target.value)}
            placeholder="automobile parts, cold chain logistics, FMCG"
          />
        </Field>

        <div className="grid grid-cols-2 gap-4">
          <Field label="City / Location *">
            <input
              className={input}
              value={form.location}
              onChange={(e) => set("location", e.target.value)}
              placeholder="Riyadh"
            />
          </Field>
          <Field label="Country">
            <input
              className={input}
              value={form.country}
              onChange={(e) => set("country", e.target.value)}
              placeholder="Saudi Arabia"
            />
          </Field>
        </div>

        <Field label="Excluded Categories" hint="Comma-separated">
          <input
            className={input}
            value={form.excluded_categories}
            onChange={(e) => set("excluded_categories", e.target.value)}
            placeholder="restaurant, clinic, school"
          />
        </Field>

        <Field
          label="Our Services"
          hint="What WE provide — used for ICP scoring and outreach only, NOT for search queries. Comma-separated."
        >
          <input
            className={input}
            value={form.our_services}
            onChange={(e) => set("our_services", e.target.value)}
            placeholder="ERP consulting, process automation, AI workflow implementation"
          />
        </Field>

        <Field
          label="Target Pain Patterns"
          hint="Observable signals of likely buyers. Comma-separated. Optional."
        >
          <input
            className={input}
            value={form.target_pain_patterns}
            onChange={(e) => set("target_pain_patterns", e.target.value)}
            placeholder="manual workflow bottlenecks, poor planning visibility"
          />
        </Field>

        <Field label="Pain Points" hint="Comma-separated">
          <input
            className={input}
            value={form.pain_points}
            onChange={(e) => set("pain_points", e.target.value)}
            placeholder="operational inefficiency, digital transformation lag"
          />
        </Field>

        <Field label="Value Proposition">
          <textarea
            className={input}
            rows={2}
            value={form.value_proposition}
            onChange={(e) => set("value_proposition", e.target.value)}
            placeholder="We help enterprises cut costs by 30% in 90 days."
          />
        </Field>

        <Field label="Notes">
          <textarea
            className={input}
            rows={2}
            value={form.notes}
            onChange={(e) => set("notes", e.target.value)}
            placeholder="Focus on established B2B companies."
          />
        </Field>

        <Field label="Language Preference">
          <select
            className={input}
            value={form.language_preference}
            onChange={(e) => set("language_preference", e.target.value)}
          >
            {LANG_OPTIONS.map((l) => <option key={l}>{l}</option>)}
          </select>
        </Field>

        {/* Continuous run toggle */}
        <div className="border border-gray-200 rounded-lg p-4 space-y-3 bg-gray-50">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-gray-700">Continuous Mode</p>
              <p className="text-xs text-gray-400 mt-0.5">
                Automatically re-run the pipeline on a schedule. Duplicate companies are skipped.
              </p>
            </div>
            <button
              type="button"
              onClick={() => setForm((f) => ({ ...f, continuous: !f.continuous }))}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                form.continuous ? "bg-blue-600" : "bg-gray-300"
              }`}
            >
              <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                form.continuous ? "translate-x-6" : "translate-x-1"
              }`} />
            </button>
          </div>
          {form.continuous && (
            <Field label="Interval (minutes)" hint="Minimum 15 minutes between runs">
              <input
                className={input}
                type="number"
                min={15}
                value={form.continuous_interval_minutes}
                onChange={(e) => setForm((f) => ({ ...f, continuous_interval_minutes: parseInt(e.target.value) || 60 }))}
              />
            </Field>
          )}
        </div>

        <button
          type="submit"
          disabled={state === "submitting"}
          className="w-full bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-sm font-medium py-2.5 rounded-md"
        >
          {state === "submitting" ? "Starting pipeline…" : "Generate Leads"}
        </button>
      </form>
    </div>
  );
}

const input =
  "w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500";

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-1">{label}</label>
      {hint && <p className="text-xs text-gray-400 mb-1">{hint}</p>}
      {children}
    </div>
  );
}
