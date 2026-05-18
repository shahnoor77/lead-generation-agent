# KSA Lead Generation System — API Documentation

**Base URL:** `http://<your-server>:8000`  
**Interactive Docs:** `http://<your-server>:8000/docs`

---

## Authentication

Every endpoint (except `/health` and `GET /api/v1/webhooks/events`) requires two headers:

| Header | Description |
|---|---|
| `X-User-Id` | Your UUID (e.g. `550e8400-e29b-41d4-a716-446655440000`) |
| `X-Api-Key` | The `OPERATOR_API_KEY` value from the server `.env` |

**First request with a new UUID auto-creates your account** (when `ALLOW_USER_SELF_REGISTRATION=true`).

```http
X-User-Id: 550e8400-e29b-41d4-a716-446655440000
X-Api-Key: your-operator-api-key
```

---

## Table of Contents

1. [Health](#1-health)
2. [Auth](#2-auth)
3. [Settings](#3-settings)
4. [Pipeline — Start & Poll](#4-pipeline--start--poll)
5. [Operations — Runs & Leads](#5-operations--runs--leads)
6. [Lead Lifecycle](#6-lead-lifecycle)
7. [Draft Finalization](#7-draft-finalization)
8. [Outreach Agent](#8-outreach-agent)
9. [Webhooks](#9-webhooks)

---

## 1. Health

### `GET /health`
Check if the server is running. No authentication required.

**Response:**
```json
{ "status": "ok" }
```

---

## 2. Auth

### `GET /api/v1/auth/me`
Validate credentials. Creates account on first use if self-registration is enabled.

**Request:**
```http
GET /api/v1/auth/me
X-User-Id: 550e8400-e29b-41d4-a716-446655440000
X-Api-Key: your-operator-api-key
```

**Response `200`:**
```json
{
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "email": null,
  "is_active": true
}
```

**Error `401`:** Invalid UUID or wrong API key.  
**Error `503`:** `OPERATOR_API_KEY` not configured on the server.

---

## 3. Settings

### `GET /api/v1/settings`
Get current user's ICP, outreach, and AI agent settings.

**Response `200`:**
```json
{
  "user_id": "550e8400-...",
  "icp": {
    "decision_maker_titles": ["CEO", "COO", "GM", "Owner"],
    "target_industries": ["manufacturing", "logistics"],
    "min_fit_score": 45,
    "require_website": false,
    "require_contact": false
  },
  "outreach": {
    "daily_send_limit": 50,
    "send_window_start": "09:00",
    "send_window_end": "17:00",
    "followup_enabled": true,
    "followup_max_attempts": 4,
    "followup_interval_hours": 48
  },
  "ai_agent": {
    "agent_mode": "semi-autonomous",
    "email_tone": "formal-business",
    "hypothesis_depth": "concise",
    "summary_depth": "standard"
  }
}
```

### `PUT /api/v1/settings`
Update settings. All groups are optional — only provided groups are changed.

**Request body (update ICP only):**
```json
{
  "icp": {
    "decision_maker_titles": ["CEO", "COO", "GM"],
    "min_fit_score": 55,
    "require_website": true
  }
}
```

**Request body (update AI agent only):**
```json
{
  "ai_agent": {
    "agent_mode": "autonomous",
    "email_tone": "executive-direct",
    "hypothesis_depth": "detailed"
  }
}
```

**`agent_mode` values:**
- `semi-autonomous` — pipeline stops after draft generation; operator reviews and manually sends
- `autonomous` — pipeline auto-approves and sends immediately after generation

**`email_tone` values:** `executive-direct` | `formal-business` | `problem-specific`  
**`hypothesis_depth` / `summary_depth`:** `concise` | `standard` | `detailed`

**Response `200`:** Same shape as GET /settings.

---

## 4. Pipeline — Start & Poll

### `POST /api/v1/leads/generate`
Start a lead generation pipeline run.

**Request body:**
```json
{
  "context": {
    "industries": ["manufacturing", "logistics"],
    "location": "Riyadh",
    "country": "Saudi Arabia",
    "domain": "automobile parts",
    "our_services": ["ERP consulting", "process automation"],
    "target_pain_patterns": ["manual workflow bottlenecks"],
    "value_proposition": "We reduce operational costs by 30%",
    "language_preference": "EN",
    "sandbox_outreach": false,
    "continuous": false
  }
}
```

**Required fields:** `industries`, `location`  
**Optional:** `country`, `domain`, `area`, `our_services`, `target_pain_patterns`, `value_proposition`, `language_preference` (`EN`|`AR`|`AUTO`), `sandbox_outreach`, `continuous`, `continuous_interval_minutes`

**Response `200`:**
```json
{
  "pipeline_run_id": "a1b2c3d4-...",
  "status": "running",
  "message": "Pipeline started. Poll GET /api/v1/leads/runs/a1b2c3d4-... for status."
}
```

### `GET /api/v1/leads/runs/{run_id}`
Poll pipeline run status.

**Response `200`:**
```json
{
  "pipeline_run_id": "a1b2c3d4-...",
  "status": "done",
  "total_discovered": 42,
  "total_enriched": 38,
  "total_filtered_out": 5,
  "total_evaluated": 33,
  "total_rejected_by_icp": 15,
  "outreach_draft_count": 18,
  "error_count": 0,
  "errors": []
}
```
**`status` values:** `running` | `done` | `failed`

### `GET /api/v1/leads/runs/{run_id}/drafts`
Get all generated outreach drafts for a run.

**Response `200`:**
```json
{
  "pipeline_run_id": "a1b2c3d4-...",
  "drafts": [
    {
      "lead_id": "lead-uuid",
      "email_subject": "Reducing operational bottlenecks at ABC Co",
      "email_body": "Dear Mr. Ahmed...",
      "language": "EN",
      "word_count": 145,
      "approved": false
    }
  ]
}
```

### `GET /api/v1/leads/runs/{run_id}/evaluated`
Get all ICP-evaluated leads for a run.

**Response `200`:**
```json
{
  "pipeline_run_id": "a1b2c3d4-...",
  "evaluated_leads": [
    {
      "lead_id": "lead-uuid",
      "company_name": "ABC Manufacturing",
      "location": "Riyadh",
      "website": "https://abc.com",
      "fit_score": 72,
      "decision": "QUALIFIED"
    }
  ]
}
```

### `GET /api/v1/leads/config`
Get the user's last-saved pipeline configuration (restored on next run form load).

### `GET /api/v1/leads/continuous`
List active continuous pipeline runs for the current user.

**Response `200`:**
```json
{ "active_continuous_runs": ["config-id-1"], "count": 1 }
```

### `DELETE /api/v1/leads/continuous/{config_id}`
Stop a continuous pipeline run.

**Response `200`:**
```json
{ "config_id": "config-id-1", "status": "stopping" }
```

---

## 5. Operations — Runs & Leads

### `GET /api/v1/runs`
List all pipeline runs for the current user, newest first.

**Response `200`:**
```json
{
  "runs": [
    {
      "run_id": "a1b2c3d4-...",
      "industries": "manufacturing, logistics",
      "domain": "automobile parts",
      "location": "Riyadh",
      "country": "Saudi Arabia",
      "started_at": "2026-05-18T10:00:00",
      "completed_at": "2026-05-18T10:15:00",
      "total_discovered": 42,
      "total_enriched": 38,
      "total_evaluated": 33,
      "total_outreach_drafts": 18,
      "sandbox_outreach": false,
      "status_summary": {
        "total_discovered": 42,
        "total_qualified": 18,
        "total_contacted": 5,
        "total_replied": 2,
        "total_won": 1
      }
    }
  ],
  "total": 1
}
```

### `GET /api/v1/runs/{run_id}/leads`
Get all evaluated leads for a run (Kanban view).

**Response `200`:**
```json
{
  "run_id": "a1b2c3d4-...",
  "pipeline_complete": true,
  "total": 18,
  "leads": [
    {
      "lead_id": "lead-uuid",
      "company_name": "ABC Manufacturing",
      "website": "https://abc.com",
      "location": "Riyadh",
      "contact_email": "info@abc.com",
      "fit_score": 72,
      "decision": "QUALIFIED",
      "current_status": "OUTREACH_DRAFTED",
      "approval_status": "PENDING_REVIEW",
      "outreach_sent": false,
      "discovered_at": "2026-05-18T10:01:00"
    }
  ]
}
```

### `GET /api/v1/runs/{run_id}/discovered`
All raw + enriched leads discovered in a run (includes rejected ones).

**Response `200`:**
```json
{
  "pipeline_run_id": "a1b2c3d4-...",
  "total": 42,
  "leads": [
    {
      "lead_id": "lead-uuid",
      "company_name": "ABC Manufacturing",
      "category": "Manufacturing",
      "location": "Riyadh",
      "address": "King Fahd Road",
      "phone": "+966500000000",
      "website": "https://abc.com",
      "contact_email": "info@abc.com",
      "linkedin_url": null,
      "industry": "manufacturing",
      "business_type": "B2B",
      "enrichment_success": true,
      "icp_decision": "QUALIFIED",
      "fit_score": 72,
      "discovered_at": "2026-05-18T10:01:00"
    }
  ]
}
```

### `GET /api/v1/leads/{lead_id}`
Full detail view for a single lead.

**Response `200`:**
```json
{
  "lead_id": "lead-uuid",
  "pipeline_run_id": "a1b2c3d4-...",
  "company": {
    "company_name": "ABC Manufacturing",
    "website": "https://abc.com",
    "location": "Riyadh",
    "address": "King Fahd Road",
    "phone": "+966500000000",
    "category": "Manufacturing",
    "rating": 4.2,
    "review_count": 38,
    "contact_email": "info@abc.com"
  },
  "intelligence": {
    "enrichment_summary": "ABC Manufacturing is a mid-size B2B firm...",
    "inferred_pain_points": ["manual inventory tracking", "poor planning visibility"],
    "icp_reasoning": "Strong fit — B2B, manufacturing, decision maker accessible",
    "rule_score": 68,
    "llm_score": 75,
    "fit_score": 72,
    "decision": "QUALIFIED"
  },
  "generated_draft": {
    "subject": "Reducing operational bottlenecks at ABC Manufacturing",
    "body": "Dear Mr. Ahmed...",
    "language": "EN",
    "word_count": 145,
    "generated_at": "2026-05-18T10:05:00"
  },
  "final_draft": null,
  "current_status": "OUTREACH_DRAFTED",
  "status_history": [
    { "status": "DISCOVERED", "changed_at": "2026-05-18T10:01:00", "changed_by": "pipeline", "notes": null },
    { "status": "OUTREACH_DRAFTED", "changed_at": "2026-05-18T10:05:00", "changed_by": "pipeline", "notes": null }
  ]
}
```

---

## 6. Lead Lifecycle

### `PATCH /api/v1/leads/{lead_id}/status`
Manually update a lead's lifecycle status.

**Request body:**
```json
{
  "status": "CONTACTED",
  "notes": "Sent intro email via LinkedIn",
  "updated_by": "john.doe"
}
```

**Valid manual statuses:** `READY_FOR_REVIEW` → `READY_TO_SEND` → `CONTACTED` → `REPLIED` → `MEETING_SCHEDULED` → `WON` | `LOST` | `ARCHIVED`

**Error `422`:** Invalid transition or pipeline-only status.

**Response `200`:**
```json
{
  "lead_id": "lead-uuid",
  "company_name": "ABC Manufacturing",
  "current_status": "CONTACTED",
  "status_updated_at": "2026-05-18T11:00:00",
  "updated_by": "john.doe",
  "notes": "Sent intro email via LinkedIn"
}
```

### `GET /api/v1/leads/{lead_id}/status`
Get current lifecycle status.

### `GET /api/v1/leads/{lead_id}/status/history`
Get full status change history for a lead.

**Response `200`:**
```json
{
  "lead_id": "lead-uuid",
  "company_name": "ABC Manufacturing",
  "current_status": "CONTACTED",
  "history": [
    { "status": "DISCOVERED", "changed_at": "2026-05-18T10:01:00", "changed_by": "pipeline", "notes": null },
    { "status": "CONTACTED", "changed_at": "2026-05-18T11:00:00", "changed_by": "john.doe", "notes": "Sent intro email" }
  ]
}
```

---

## 7. Draft Finalization

### `PATCH /api/v1/leads/{lead_id}/finalize-draft`
Save the human-edited final draft. Moves lead to `READY_FOR_REVIEW`. Can be called multiple times to update.

**Request body:**
```json
{
  "final_subject": "Reducing operational bottlenecks at ABC Manufacturing",
  "final_body": "Dear Mr. Ahmed,\n\nI hope this message finds you well...",
  "receiver_details": {
    "receiver_name": "Ahmed Khan",
    "receiver_role": "Operations Director",
    "receiver_email": "ahmed@abc.com",
    "linkedin_url": null,
    "preferred_contact_method": "email"
  },
  "sender_details": {
    "sender_name": "Ali Hassan",
    "sender_role": "Business Consultant",
    "sender_company": "XYZ Consulting",
    "sender_email": "ali@xyz.com",
    "sender_phone": "+966500000000",
    "signature": "Best regards,\nAli Hassan"
  },
  "finalized_by": "ali.hassan",
  "notes": "Adjusted tone for manufacturing sector"
}
```

**Response `200`:**
```json
{
  "lead_id": "lead-uuid",
  "company_name": "ABC Manufacturing",
  "generated_subject": "Original AI subject",
  "generated_body": "Original AI body...",
  "generated_at": "2026-05-18T10:05:00",
  "final_subject": "Reducing operational bottlenecks at ABC Manufacturing",
  "final_body": "Dear Mr. Ahmed...",
  "finalized_at": "2026-05-18T11:30:00",
  "finalized_by": "ali.hassan",
  "receiver_details": { "receiver_name": "Ahmed Khan", "receiver_email": "ahmed@abc.com", "..." : "..." },
  "sender_details": { "sender_name": "Ali Hassan", "sender_email": "ali@xyz.com", "..." : "..." },
  "approval_status": "PENDING_REVIEW",
  "approved_by": null,
  "approved_at": null,
  "lifecycle_status": "READY_FOR_REVIEW"
}
```

### `GET /api/v1/leads/{lead_id}/finalize-draft`
Retrieve the current finalized draft for a lead.

---

## 8. Outreach Agent

### Sender Account

#### `GET /api/v1/outreach/account`
Get the current user's configured sender SMTP/IMAP identity (no passwords returned).

**Response `200`:**
```json
{
  "configured": true,
  "id": 1,
  "email_address": "ali@xyz.com",
  "display_name": "Ali Hassan — XYZ Consulting",
  "smtp_host": "smtp.gmail.com",
  "smtp_port": 587,
  "smtp_username": "ali@xyz.com",
  "smtp_password_configured": true,
  "use_tls": true,
  "daily_limit": 50,
  "imap_host": "imap.gmail.com",
  "imap_port": 993,
  "imap_username": "ali@xyz.com",
  "imap_password_configured": true,
  "imap_use_ssl": true,
  "is_active": true
}
```

#### `PUT /api/v1/outreach/account`
Create or update sender credentials. Omit `smtp_password` / `imap_password` on update to keep existing.

**Request body:**
```json
{
  "email_address": "ali@xyz.com",
  "display_name": "Ali Hassan — XYZ Consulting",
  "smtp_host": "smtp.gmail.com",
  "smtp_port": 587,
  "smtp_username": "ali@xyz.com",
  "smtp_password": "app-password-here",
  "use_tls": true,
  "daily_limit": 50,
  "imap_host": "imap.gmail.com",
  "imap_port": 993,
  "imap_username": "ali@xyz.com",
  "imap_password": "app-password-here",
  "imap_use_ssl": true
}
```

### Outreach Jobs

#### `POST /api/v1/outreach/jobs/start`
Start a continuous outreach job (sends emails on a schedule).

**Request body:**
```json
{ "interval_minutes": 60 }
```

**Response `200`:**
```json
{
  "status": "started",
  "user_id": "550e8400-...",
  "interval_minutes": 60,
  "message": "Outreach job started. Stop via DELETE /api/v1/outreach/jobs/stop"
}
```

#### `DELETE /api/v1/outreach/jobs/stop`
Stop the running outreach job. Current cycle completes before stopping.

#### `GET /api/v1/outreach/jobs/status`
Get job status and today's send count.

**Response `200`:**
```json
{
  "is_running": true,
  "sent_today": 12,
  "sender_email": "ali@xyz.com",
  "daily_limit": 50
}
```

#### `POST /api/v1/outreach/run-now`
Trigger one outreach cycle immediately (manual, no schedule).

**Response `200`:**
```json
{ "status": "completed", "sent": 3, "skipped": 2, "failed": 0 }
```

### Send Individual Lead

#### `POST /api/v1/outreach/send-lead`
Send outreach for a single specific lead.

**Request body:**
```json
{
  "lead_id": "lead-uuid",
  "receiver_email": "ahmed@abc.com"
}
```
`receiver_email` is optional — falls back to finalized receiver or enriched contact email.

**Response `200`:**
```json
{
  "status": "sent",
  "lead_id": "lead-uuid",
  "receiver_email": "ahmed@abc.com",
  "smtp_envelope_to": "ahmed@abc.com",
  "sandbox_routing": false
}
```

### Sent Log

#### `GET /api/v1/outreach/sent?limit=100`
Get the sent email log for the current user.

**Response `200`:**
```json
{
  "total": 15,
  "sent": [
    {
      "lead_id": "lead-uuid",
      "sender_email": "ali@xyz.com",
      "receiver_email": "ahmed@abc.com",
      "subject": "Reducing operational bottlenecks...",
      "status": "sent",
      "campaign_stage": "initial",
      "sent_at": "2026-05-18T12:00:00",
      "error": null
    }
  ]
}
```

### Sandbox Test Inboxes

Used when `sandbox_outreach: true` in pipeline runs — SMTP is routed to test addresses instead of real leads.

#### `GET /api/v1/outreach/sandbox/inboxes`
List configured sandbox inboxes.

#### `PUT /api/v1/outreach/sandbox/inboxes`
Replace all sandbox inboxes.
```json
{ "emails": ["test1@yourdomain.com", "test2@yourdomain.com"] }
```

#### `DELETE /api/v1/outreach/sandbox/inboxes/{id}`
Remove a specific sandbox inbox.

#### `DELETE /api/v1/outreach/sandbox/lead-recipient-map`
Clear persisted lead→sandbox assignments (reset before a new sandbox campaign).

---

## 9. Webhooks

Webhooks let your server push events to any external URL automatically — no polling needed.

### How It Works

1. You register a URL with the events you want
2. When those events happen, the server POSTs a JSON payload to your URL
3. Your server receives it and does whatever it needs (update UI, trigger notifications, sync CRM, etc.)

### Outgoing Request Format

Every webhook delivery is a `POST` to your URL with these headers:

```
Content-Type: application/json
X-Webhook-Event: run.completed
User-Agent: LeadGen-Webhook/1.0
```

And this JSON body:
```json
{
  "event": "run.completed",
  "event_id": "uuid-for-dedup",
  "timestamp": "2026-05-18T10:30:00Z",
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "data": {
    "...event specific fields..."
  }
}
```

Your endpoint should return any `2xx` status. Failed deliveries are retried up to 3 times.

---

### Supported Events

| Event | Fired When |
|---|---|
| `run.completed` | A pipeline run finishes |
| `lead.status_changed` | Any lead lifecycle status changes (pipeline or human) |
| `lead.discovered` | A new lead is found by discovery |
| `lead.qualified` | A lead passes ICP evaluation |
| `lead.outreach_drafted` | An outreach email draft is generated |
| `outreach.sent` | An email is sent to a lead (initial or follow-up) |
| `outreach.replied` | A prospect replies to an outreach email |
| `outreach.meeting` | A meeting handoff is created from a positive reply |
| `draft.finalized` | A human finalizes an outreach draft |

#### `GET /api/v1/webhooks/events`
Returns this list with descriptions. No authentication required.

---

### Event Payloads

#### `run.completed`
```json
{
  "event": "run.completed",
  "data": {
    "run_id": "a1b2c3d4-...",
    "agent_mode": "semi-autonomous",
    "sandbox_outreach": false,
    "total_discovered": 42,
    "total_enriched": 38,
    "total_filtered_out": 5,
    "total_evaluated": 33,
    "total_rejected_by_icp": 15,
    "total_outreach_drafts": 18,
    "total_auto_sent": 0,
    "errors": 0
  }
}
```

#### `lead.status_changed`
```json
{
  "event": "lead.status_changed",
  "data": {
    "lead_id": "lead-uuid",
    "company_name": "ABC Manufacturing",
    "pipeline_run_id": "a1b2c3d4-...",
    "status": "CONTACTED",
    "changed_by": "john.doe",
    "notes": "Sent intro email",
    "changed_at": "2026-05-18T11:00:00Z"
  }
}
```

#### `outreach.sent`
```json
{
  "event": "outreach.sent",
  "data": {
    "lead_id": "lead-uuid",
    "company_name": "ABC Manufacturing",
    "receiver_email": "ahmed@abc.com",
    "subject": "Reducing operational bottlenecks...",
    "campaign_stage": "initial",
    "followup_number": 0,
    "sender_email": "ali@xyz.com"
  }
}
```

#### `draft.finalized`
```json
{
  "event": "draft.finalized",
  "data": {
    "lead_id": "lead-uuid",
    "company_name": "ABC Manufacturing",
    "pipeline_run_id": "a1b2c3d4-...",
    "final_subject": "Reducing operational bottlenecks...",
    "receiver_email": "ahmed@abc.com",
    "finalized_by": "ali.hassan",
    "approval_status": "PENDING_REVIEW"
  }
}
```

---

### Webhook Management Endpoints

All require `X-User-Id` + `X-Api-Key`.

#### `POST /api/v1/webhooks` — Register a webhook
```json
{
  "url": "https://yourapp.com/hooks/leadgen",
  "events": ["run.completed", "lead.status_changed", "outreach.sent"],
  "description": "My app webhook"
}
```

**Response `201`:**
```json
{
  "id": 1,
  "user_id": "550e8400-...",
  "url": "https://yourapp.com/hooks/leadgen",
  "events": ["run.completed", "lead.status_changed", "outreach.sent"],
  "description": "My app webhook",
  "is_active": true,
  "created_at": "2026-05-18T10:00:00",
  "updated_at": "2026-05-18T10:00:00"
}
```

#### `GET /api/v1/webhooks` — List all registered webhooks
```json
{
  "webhooks": [ { "id": 1, "url": "...", "events": [...], "is_active": true, "..." : "..." } ],
  "total": 1
}
```

#### `GET /api/v1/webhooks/{id}` — Get a single webhook

#### `PATCH /api/v1/webhooks/{id}` — Update a webhook
All fields optional. Set `is_active: false` to pause without deleting.
```json
{
  "events": ["run.completed"],
  "is_active": false
}
```

#### `DELETE /api/v1/webhooks/{id}` — Delete a webhook
Returns `204 No Content`.

---

## Error Reference

| Code | Meaning |
|---|---|
| `401` | Invalid UUID or wrong API key |
| `403` | Account disabled or forbidden action |
| `404` | Resource not found |
| `422` | Validation error or invalid status transition |
| `503` | `OPERATOR_API_KEY` not configured on server |

---

## Lead Lifecycle Status Reference

| Status | Set By | Description |
|---|---|---|
| `DISCOVERED` | Pipeline | Raw lead found by discovery |
| `ENRICHED` | Pipeline | Website scraped and summarized |
| `QUALIFIED` | Pipeline | Passed ICP evaluation |
| `OUTREACH_DRAFTED` | Pipeline | Email draft generated |
| `READY_FOR_REVIEW` | Human / Finalization | Draft finalized, awaiting approval |
| `READY_TO_SEND` | Human | Approved, ready to send |
| `CONTACTED` | Agent / Human | Outreach email sent |
| `REPLIED` | Agent / Human | Prospect replied |
| `MEETING_SCHEDULED` | Agent / Human | Meeting booked |
| `WON` | Human | Deal confirmed |
| `LOST` | Agent / Human | No longer pursuing |
| `ARCHIVED` | Human | Removed from active pipeline |
