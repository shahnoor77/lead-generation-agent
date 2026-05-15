const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const { getToken } = await import("@/lib/auth");
  const token = getToken();
  const res = await fetch(`${BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init?.headers,
    },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

function _isHttp404Error(err: unknown): boolean {
  return err instanceof Error && err.message.startsWith("404:");
}

/**
 * Newer API exposes GET/PUT /api/v1/outreach/account. Older servers only have /outreach/accounts.
 * These helpers fall back so Settings still works if the backend process was not restarted.
 */
async function getOutreachAccountWithFallback(): Promise<Record<string, unknown>> {
  try {
    return await request<Record<string, unknown>>("/api/v1/outreach/account");
  } catch (e: unknown) {
    if (!_isHttp404Error(e)) throw e;
    const legacy = await request<{ accounts?: Record<string, unknown>[] }>("/api/v1/outreach/accounts");
    const list = legacy.accounts ?? [];
    const active = list.find((a) => a.is_active) ?? list[0];
    if (!active) return { configured: false };
    const smtpUser = (active.smtp_username as string) ?? (active.email_address as string) ?? "";
    return {
      configured: true,
      id: active.id,
      email_address: active.email_address,
      display_name: (active.display_name as string) ?? "",
      smtp_host: active.smtp_host,
      smtp_port: typeof active.smtp_port === "number" ? active.smtp_port : 587,
      smtp_username: smtpUser,
      smtp_password_configured: true,
      use_tls: active.use_tls !== false,
      daily_limit: typeof active.daily_limit === "number" ? active.daily_limit : 50,
      imap_host: (active.imap_host as string | null | undefined) ?? null,
      imap_port: typeof active.imap_port === "number" ? active.imap_port : 993,
      imap_username: (active.imap_username as string | null | undefined) ?? null,
      imap_password_configured: Boolean(active.imap_password_configured),
      imap_use_ssl: active.imap_use_ssl !== false,
      is_active: active.is_active !== false,
    };
  }
}

async function saveOutreachAccountWithFallback(
  payload: Record<string, unknown>
): Promise<Record<string, unknown>> {
  const { getToken } = await import("@/lib/auth");
  const token = getToken();
  const headers: HeadersInit = {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
  const res = await fetch(`${BASE}/api/v1/outreach/account`, {
    method: "PUT",
    headers,
    body: JSON.stringify(payload),
  });
  if (res.status === 404) {
    await request("/api/v1/outreach/accounts", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    return getOutreachAccountWithFallback();
  }
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json() as Promise<Record<string, unknown>>;
}

// ── Types ──────────────────────────────────────────────────────────────────

export interface RunStatusSummary {
  total_discovered: number;
  total_enriched: number;
  total_qualified: number;
  total_outreach_drafted: number;
  total_ready_for_review: number;
  total_ready_to_send: number;
  total_contacted: number;
  total_replied: number;
  total_meetings: number;
  total_won: number;
  total_lost: number;
}

export interface PipelineRun {
  run_id: string;
  industries: string;
  domain: string | null;
  location: string;
  country: string | null;
  started_at: string;
  completed_at: string | null;
  total_discovered: number;
  total_enriched: number;
  total_evaluated: number;
  total_outreach_drafts: number;
  /** True when outbound was routed to sandbox test inboxes */
  sandbox_outreach?: boolean;
  status_summary: RunStatusSummary;
}

export interface LeadSummary {
  lead_id: string;
  company_name: string;
  website: string | null;
  location: string;
  contact_email?: string | null;
  fit_score: number;
  decision: string;
  current_status: string | null;
  approval_status: string | null;
  /** True if this user already sent outbound mail logged for this lead */
  outreach_sent?: boolean;
  discovered_at: string;
}

export interface StatusHistoryEntry {
  status: string;
  changed_at: string;
  changed_by: string | null;
  notes: string | null;
}

export interface LeadDetail {
  lead_id: string;
  pipeline_run_id: string;
  company: {
    company_name: string;
    website: string | null;
    location: string;
    address: string | null;
    phone: string | null;
    category: string | null;
    rating: number | null;
    review_count: number | null;
    /** Enriched discovery email — used automatically for outbound (not edited here) */
    contact_email?: string | null;
  };
  intelligence: {
    enrichment_summary: string | null;
    inferred_pain_points: string[];
    icp_reasoning: string | null;
    rule_score: number;
    llm_score: number | null;
    fit_score: number;
    decision: string;
  };
  generated_draft: {
    subject: string;
    body: string;
    language: string;
    word_count: number;
    generated_at: string;
  } | null;
  final_draft: {
    subject: string;
    body: string;
    finalized_at: string;
    finalized_by: string | null;
    approval_status: string;
    approved_by: string | null;
    approved_at: string | null;
    receiver: ReceiverDetails;
    sender: SenderDetails;
  } | null;
  current_status: string | null;
  status_history: StatusHistoryEntry[];
}

export interface ReceiverDetails {
  receiver_name: string;
  receiver_role: string | null;
  receiver_email: string;
  linkedin_url: string | null;
  preferred_contact_method: string | null;
}

export interface SenderDetails {
  sender_name: string;
  sender_role: string | null;
  sender_company: string | null;
  sender_email: string;
  sender_phone: string | null;
  signature: string | null;
}

export interface DiscoveredLead {
  lead_id: string;
  company_name: string;
  category: string | null;
  location: string;
  address: string | null;
  phone: string | null;
  website: string | null;
  contact_email: string | null;
  linkedin_url: string | null;
  industry: string | null;
  business_type: string | null;
  enrichment_success: boolean;
  icp_decision: string | null;
  fit_score: number | null;
  discovered_at: string | null;
}

export interface StartRunPayload {
  context: {
    industries: string[];
    location: string;
    country?: string;
    domain?: string;
    area?: string;
    excluded_categories?: string[];
    our_services?: string[];
    target_pain_patterns?: string[];
    pain_points?: string[];
    value_proposition?: string;
    language_preference?: string;
    notes?: string;
    /** When true, SMTP uses sandbox inboxes; never combined with continuous mode */
    sandbox_outreach?: boolean;
    continuous?: boolean;
    continuous_interval_minutes?: number;
  };
}

// ── API calls ──────────────────────────────────────────────────────────────

export const api = {
  // Auth
  signup: (email: string, password: string) =>
    request<{ user_id: number; email: string }>("/api/v1/auth/signup", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  login: async (email: string, password: string) => {
    const form = new URLSearchParams({ username: email, password });
    const res = await fetch(`${BASE}/api/v1/auth/token`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: form.toString(),
    });
    if (!res.ok) throw new Error("Invalid email or password");
    return res.json() as Promise<{ access_token: string; user_id: number; email: string }>;
  },
  me: () => request<{ user_id: number; email: string }>("/api/v1/auth/me"),
  getSettings: () => request<Record<string, unknown>>("/api/v1/settings"),
  saveSettings: (settings: Record<string, unknown>) =>
    request("/api/v1/settings", { method: "PUT", body: JSON.stringify(settings) }),
  getSavedConfig: () => request<{ config: Record<string, unknown> | null }>("/api/v1/leads/config"),
  getRuns: () => request<{ runs: PipelineRun[]; total: number }>("/api/v1/runs"),
  startRun: (payload: StartRunPayload) =>
    request<{ pipeline_run_id: string; status: string; message: string }>(
      "/api/v1/leads/generate",
      { method: "POST", body: JSON.stringify(payload) }
    ),
  pollRun: (runId: string) =>
    request<{ status: string; total_discovered: number; outreach_draft_count: number }>(
      `/api/v1/leads/runs/${runId}`
    ),

  // Leads
  getRunDiscovered: (runId: string) =>
    request<{ pipeline_run_id: string; total: number; leads: DiscoveredLead[] }>(
      `/api/v1/runs/${runId}/discovered`
    ),
  getRunLeads: (runId: string) =>
    request<{ run_id: string; pipeline_complete: boolean; leads: LeadSummary[]; total: number }>(
      `/api/v1/runs/${runId}/leads`
    ),
  getLeadDetail: (leadId: string) => request<LeadDetail>(`/api/v1/leads/${leadId}`),

  stopContinuous: (configId: string) =>
    request(`/api/v1/leads/continuous/${configId}`, { method: "DELETE" }),
  listContinuous: () =>
    request<{ active_continuous_runs: string[]; count: number }>("/api/v1/leads/continuous"),

  // Outreach Agent — persisted per-user sender (GET/PUT /account, with legacy fallbacks)
  getOutreachAccount: () => getOutreachAccountWithFallback(),
  saveOutreachAccount: (payload: Record<string, unknown>) =>
    saveOutreachAccountWithFallback(payload),
  getOutreachAccounts: () => request("/api/v1/outreach/accounts"),
  addOutreachAccount: (payload: object) =>
    request("/api/v1/outreach/accounts", { method: "POST", body: JSON.stringify(payload) }),
  removeOutreachAccount: (id: number) =>
    request(`/api/v1/outreach/accounts/${id}`, { method: "DELETE" }),
  startOutreachJob: (intervalMinutes: number) =>
    request("/api/v1/outreach/jobs/start", { method: "POST", body: JSON.stringify({ interval_minutes: intervalMinutes }) }),
  stopOutreachJob: () =>
    request("/api/v1/outreach/jobs/stop", { method: "DELETE" }),
  getOutreachJobStatus: () => request("/api/v1/outreach/jobs/status"),
  runOutreachNow: () => request("/api/v1/outreach/run-now", { method: "POST" }),
  listSandboxInboxes: () =>
    request<{ inboxes: { id: number; email: string; is_active: boolean }[]; total: number }>(
      "/api/v1/outreach/sandbox/inboxes"
    ),
  replaceSandboxInboxes: (emails: string[]) =>
    request<{ status: string; count: number }>("/api/v1/outreach/sandbox/inboxes", {
      method: "PUT",
      body: JSON.stringify({ emails }),
    }),
  deleteSandboxInboxRow: (id: number) =>
    request(`/api/v1/outreach/sandbox/inboxes/${id}`, { method: "DELETE" }),
  clearSandboxLeadMap: () =>
    request("/api/v1/outreach/sandbox/lead-recipient-map", { method: "DELETE" }),
  sendLeadOutreach: (leadId: string, receiverEmail?: string) =>
    request("/api/v1/outreach/send-lead", {
      method: "POST",
      body: JSON.stringify({ lead_id: leadId, receiver_email: receiverEmail || undefined }),
    }),
  getOutreachSentLog: (limit = 100) => request(`/api/v1/outreach/sent?limit=${limit}`),
  getMeetingHandoffs: (status?: string, limit = 100) =>
    request(`/api/v1/outreach/meeting-handoffs?${new URLSearchParams({
      ...(status ? { status } : {}),
      limit: String(limit),
    }).toString()}`),
  updateStatus: (leadId: string, status: string, notes?: string, updatedBy?: string) =>
    request(`/api/v1/leads/${leadId}/status`, {
      method: "PATCH",
      body: JSON.stringify({ status, notes, updated_by: updatedBy }),
    }),

  // Finalization
  finalizeDraft: (leadId: string, payload: object) =>
    request(`/api/v1/leads/${leadId}/finalize-draft`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
};
