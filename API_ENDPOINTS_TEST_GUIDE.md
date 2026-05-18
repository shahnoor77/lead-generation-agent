# API Endpoints Test Guide

Base URL (local): `http://127.0.0.1:8000`

## 1) Health

- `GET /health`
- Purpose: basic service health/version check.

Quick test:

```bash
curl http://127.0.0.1:8000/health
```

Expected:

```json
{"status":"ok","version":"1.0.0"}
```

---

## 2) Auth (API key + user UUID)

All endpoints below (except `/health`) require:

- `X-User-Id: <operator-uuid>`
- `X-Api-Key: <OPERATOR_API_KEY from server .env>`

### Self-registration (default: enabled)

On the **first** request with a **new UUID** and the correct **OPERATOR_API_KEY**, the server **creates that user**.

Set `ALLOW_USER_SELF_REGISTRATION=false` in `.env` to require pre-provisioned UUIDs only.

Optional admin CLI (server-generated UUID):

```bash
set PYTHONPATH=.
python scripts/create_api_user.py --email demo@example.com
```

### Validate / register via me
- `GET /api/v1/auth/me`

```bash
curl http://127.0.0.1:8000/api/v1/auth/me \
  -H "X-User-Id: 550e8400-e29b-41d4-a716-446655440000" \
  -H "X-Api-Key: YOUR_OPERATOR_API_KEY"
```

Use the same headers on all protected routes.

---

## 3) Lead Generation + Run Monitoring

### Start run
- `POST /api/v1/leads/generate`
- Starts background pipeline and returns `pipeline_run_id`.

```bash
curl -X POST http://127.0.0.1:8000/api/v1/leads/generate \
  -H "X-User-Id: YOUR-UUID" \
  -H "X-Api-Key: YOUR_OPERATOR_API_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"context\": {
      \"industries\": [\"manufacturing\"],
      \"location\": \"Riyadh\",
      \"country\": \"Saudi Arabia\",
      \"domain\": \"business transformation\",
      \"excluded_categories\": [],
      \"our_services\": [\"process optimization\"],
      \"pain_points\": [\"operational inefficiency\"],
      \"value_proposition\": \"We improve operational efficiency.\",
      \"language_preference\": \"EN\",
      \"continuous\": false,
      \"continuous_interval_minutes\": 60
    }
  }"
```

### Poll run status
- `GET /api/v1/leads/runs/{run_id}`

```bash
curl http://127.0.0.1:8000/api/v1/leads/runs/RUN_ID \
  -H "Authorization: Bearer TOKEN"
```

### Run drafts
- `GET /api/v1/leads/runs/{run_id}/drafts`

### Run evaluated leads
- `GET /api/v1/leads/runs/{run_id}/evaluated`

### Continuous mode controls
- `GET /api/v1/leads/continuous`
- `DELETE /api/v1/leads/continuous/{config_id}`

### Saved lead-generation config
- `GET /api/v1/leads/config`

---

## 4) Operational Views (for UI pages)

### Runs list
- `GET /api/v1/runs`

### Leads in run (kanban source)
- `GET /api/v1/runs/{run_id}/leads`

### Lead full detail
- `GET /api/v1/leads/{lead_id}`

### Run discovered leads
- `GET /api/v1/runs/{run_id}/discovered`

All above require bearer token.

---

## 5) Lifecycle Management

### Update lead status
- `PATCH /api/v1/leads/{lead_id}/status`

```bash
curl -X PATCH http://127.0.0.1:8000/api/v1/leads/LEAD_ID/status \
  -H "X-User-Id: YOUR-UUID" \
  -H "X-Api-Key: YOUR_OPERATOR_API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"status\":\"CONTACTED\",\"notes\":\"manual update\",\"updated_by\":\"operator\"}"
```

### Current status
- `GET /api/v1/leads/{lead_id}/status`

### Status history
- `GET /api/v1/leads/{lead_id}/status/history`

---

## 6) Draft Finalization

### Finalize / re-finalize draft
- `PATCH /api/v1/leads/{lead_id}/finalize-draft`

### Get finalized draft
- `GET /api/v1/leads/{lead_id}/finalize-draft`

Notes:
- Generated draft is preserved.
- Finalized draft is editable.
- Lifecycle moves to `READY_FOR_REVIEW`.

---

## 7) User Settings

### Get settings
- `GET /api/v1/settings`

### Update settings
- `PUT /api/v1/settings`

Supports `icp`, `outreach`, and `ai_agent` blocks (partial updates allowed).

---

## 8) Outreach Agent

### Sender account management
- `POST /api/v1/outreach/accounts`
- `GET /api/v1/outreach/accounts`
- `DELETE /api/v1/outreach/accounts/{account_id}`

### Job controls
- `POST /api/v1/outreach/jobs/start`
- `DELETE /api/v1/outreach/jobs/stop`
- `GET /api/v1/outreach/jobs/status`
- `POST /api/v1/outreach/run-now`

### Send by industry
- `POST /api/v1/outreach/send-by-industry`

### Logs + KPIs
- `GET /api/v1/outreach/sent`
- `GET /api/v1/outreach/metrics?days=30`

---

## Quick End-to-End Smoke Sequence

1. `GET /health`
2. `POST /api/v1/auth/signup`
3. `POST /api/v1/auth/token`
4. `POST /api/v1/leads/generate` (save `RUN_ID`)
5. Poll `GET /api/v1/leads/runs/{RUN_ID}` until `status = done`
6. `GET /api/v1/runs/{RUN_ID}/leads`
7. Pick `LEAD_ID` -> `GET /api/v1/leads/{LEAD_ID}`
8. Finalize draft -> `PATCH /api/v1/leads/{LEAD_ID}/finalize-draft`
9. Add sender account -> `POST /api/v1/outreach/accounts`
10. Trigger cycle -> `POST /api/v1/outreach/run-now`
11. Verify outcomes -> `GET /api/v1/outreach/sent` and `GET /api/v1/outreach/metrics`

