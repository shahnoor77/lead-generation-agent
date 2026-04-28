# KSA B2B Lead Generation System

> Precision-targeted lead generation for Business Transformation Consulting in Saudi Arabia.
> Discovers, enriches, scores, and drafts outreach — all in one automated pipeline.

---

## What It Does

```
  User Request
      │
      ▼
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│   POST /api/v1/leads/generate  ──►  Returns run_id instantly   │
│                                     Pipeline runs in background │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
      │
      ▼
  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
  │  STAGE 1 │    │  STAGE 2 │    │  STAGE 3 │    │  STAGE 4 │    │  STAGE 5 │
  │          │    │          │    │          │    │          │    │          │
  │Discovery │───►│Enrichment│───►│  Filter  │───►│   ICP    │───►│ Outreach │
  │          │    │          │    │          │    │Evaluation│    │  Draft   │
  └──────────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘
       │               │               │               │               │
  Google Maps     Website +        Data quality    Rules + LLM     EN email
  + Web Search    LLM summary      gate            scoring         draft
       │               │               │               │               │
       ▼               ▼               ▼               ▼               ▼
  raw_leads      enriched_leads  filtered_leads  evaluated_leads  outreach_drafts
                                                                  (approved=false)
```

---

## Pipeline Stages

### ① Discovery
Searches **Google Maps** and **Google Web** for companies matching your industries and location.
Each listing is clicked to extract the full detail panel — name, address, phone, website, category, rating.

```
Query pattern:  "{industry} {domain} companies in {area} {location} {country}"

Example:        "manufacturing business transformation companies in Riyadh Saudi Arabia"
```

### ② Enrichment
Visits each company website, scrapes homepage + about pages, then calls the LLM to produce a 2–3 sentence summary.

```
Extracts:  summary · services · key people · contact email · LinkedIn · founding year · language
Model:     qwen2.5:14b  (via Ollama)
Fallback:  if LLM fails → raw text used as summary
```

### ③ Filter Layer
Pure Python — no LLM. Discards leads that are structurally unfit before spending tokens on ICP.

```
Checks (in order):
  ✗  Duplicate within this run
  ✗  Enrichment hard-failed (scrape crashed)
  ✗  Excluded category (caller-defined)
  ✗  Outside target region
  ✓  Passes all → proceeds to ICP
```

### ④ ICP Evaluation
Two-layer scoring: fast rules first, LLM only when rules pass threshold.

```
Rule Engine (always runs):
  · has_website          · industry_match
  · has_contact          · not_micro_business
  · location_presence

  rule_score = (passed / 5) × 100

LLM Scorer (only if rule_score ≥ 45):
  · Model: qwen2.5-coder:14b
  · Returns: score (0–100) · confidence · reasoning

  fit_score = avg(rule_score, llm_score)
  decision  = QUALIFIED if fit_score ≥ 45 else REJECTED
```

### ⑤ Outreach Generation
Generates a personalized English email draft for every QUALIFIED lead.

```
Before drafting:
  · Infers 2–3 company-specific pain points (rule signals + LLM)
  · Resolves language (always EN in current config)

Draft rules enforced by prompt:
  · Max 300 words
  · Hypothesis language only ("companies like yours may face...")
  · No generic openers · No competitor mentions
  · Soft CTA — 20-minute call suggestion

Output:  approved=false  ← human must review before any send
```

---

## Data Flow

```
BusinessContext (user input)
    │
    ├─► RawLead          [status=raw]           ── saved to raw_leads
    ├─► EnrichedLead     [status=enriched]       ── saved to enriched_leads
    ├─► FilteredLead     [status=filtered]       ── saved to filtered_leads
    ├─► EvaluatedLead    [status=evaluated]      ── saved to evaluated_leads
    └─► OutreachOutput   [approved=false]        ── saved to outreach_drafts
```

Every record carries `lead_id · trace_id · pipeline_run_id` for full traceability.

---

## API

```
POST  /api/v1/leads/generate          Start pipeline (returns run_id immediately)
GET   /api/v1/leads/runs/{run_id}     Poll status + counters
GET   /api/v1/leads/runs/{run_id}/drafts      Get outreach drafts
GET   /api/v1/leads/runs/{run_id}/evaluated   Get evaluated leads
GET   /health                         Health check
```

**Start a run:**
```json
POST /api/v1/leads/generate
{
  "context": {
    "industries": ["manufacturing", "logistics"],
    "location": "Riyadh",
    "country": "Saudi Arabia",
    "domain": "business transformation",
    "excluded_categories": ["restaurant", "clinic"],
    "pain_points": ["operational inefficiency", "digital transformation lag"],
    "value_proposition": "We help KSA enterprises cut costs by 30% in 90 days.",
    "language_preference": "EN",
    "notes": "Focus on established B2B companies."
  }
}
```

**Poll status:**
```json
GET /api/v1/leads/runs/{run_id}

{
  "status": "done",
  "total_discovered": 37,
  "total_enriched": 37,
  "total_filtered_out": 5,
  "total_evaluated": 32,
  "total_rejected_by_icp": 1,
  "outreach_draft_count": 31
}
```

---

## Database

Six PostgreSQL tables — one per pipeline stage:

```
 Table               Purpose
 ─────────────────── ──────────────────────────────────────────────
 pipeline_runs       One row per API call — counters + metadata
 raw_leads           Every company found by discovery
 enriched_leads      Website data + LLM summary per company
 filtered_leads      Discarded leads with reason (audit trail)
 evaluated_leads     ICP scores, decisions, LLM reasoning
 outreach_drafts     Email drafts — approved=false until human acts
```

---

## Tech Stack

```
 Layer          Technology
 ────────────── ──────────────────────────────────────────────────
 API            FastAPI + Uvicorn
 Pipeline       Python async (background tasks)
 LLM            Ollama  ·  qwen2.5-coder:14b (ICP + outreach)
                         ·  qwen2.5:14b (summarization)
 Scraping       Playwright (Google Maps)  ·  httpx + BeautifulSoup (web)
 Database       PostgreSQL + SQLModel + asyncpg
 Validation     Pydantic v2 (frozen schemas, computed fields)
 Logging        structlog (JSON in prod, colored in dev)
```

---

## Quick Start

```bash
# 1. Install dependencies
pip install poetry
poetry install

# 2. Install Playwright browser
playwright install chromium

# 3. Configure environment
cp .env.example .env
# Set DATABASE_URL and OLLAMA_BASE_URL

# 4. Create DB tables
python -c "import asyncio; from app.storage.database import init_db; asyncio.run(init_db())"

# 5. Start server
uvicorn app.main:app --host 0.0.0.0 --port 8000

# 6. Run contract tests (no network needed)
pytest tests/test_pipeline_contracts.py tests/test_pipeline_schemas.py -q
```

---

## Environment Variables

```bash
# LLM (Ollama — no API key needed)
OLLAMA_BASE_URL=http://your-ollama-host:11434
OLLAMA_MODEL=qwen2.5-coder:14b
OLLAMA_SUMMARIZE_MODEL=qwen2.5:14b

# Database
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/leadgen

# App
APP_ENV=development
LOG_LEVEL=INFO
SCRAPE_TIMEOUT_SECONDS=30
```

---

## Human Review Gate

```
  Pipeline produces drafts
          │
          ▼
  outreach_drafts  (approved = false)
          │
          │   ← Human reviews each draft
          │   ← Edits if needed
          │   ← Sets approved = true manually
          │
          ▼
  Send via preferred channel
  (system never sends automatically)
```

---

## Proven Results

Last run against Riyadh manufacturing + logistics:

```
  Discovered   37 companies
  Enriched     37 websites scraped + summarized
  Filtered      5 discarded (excluded category / outside region)
  Evaluated    32 ICP-scored  (31 QUALIFIED · 1 REJECTED)
  Drafts       31 English outreach emails  (approved=false)
  Errors        0
```
