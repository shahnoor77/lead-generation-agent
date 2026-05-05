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
  status_summary: RunStatusSummary;
}

export interface LeadSummary {
  lead_id: string;
  company_name: string;
  website: string | null;
  location: string;
  fit_score: number;
  decision: string;
  current_status: string | null;
  approval_status: string | null;
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
