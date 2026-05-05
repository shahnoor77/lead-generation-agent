"""
Pain Point Inference
--------------------
Dynamically infers 2–3 likely business challenges per company before outreach.

Design decisions:
- Runs as a lightweight async helper inside the outreach module.
- Does NOT persist results — pain points are ephemeral, used only for this draft.
- Uses the same Ollama client and model as the rest of the pipeline.
- Falls back gracefully to context.pain_points (or []) on any failure.
- Rule-based signals are derived first (free, instant) and passed to the LLM
  as additional context to improve specificity.
"""

from __future__ import annotations
import json

from app.core.config import settings
from app.core.logging import get_logger
from app.schemas import EnrichedLead, EvaluatedLead, BusinessContext
from app.utils.prompt_loader import load_prompt
from app.utils.llm_client import llm_chat

logger = get_logger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Rule-based signal derivation (free, no LLM)
# Produces short, factual observations that give the LLM richer context.
# ──────────────────────────────────────────────────────────────────────────────

# Industry → likely operational challenge patterns
_INDUSTRY_SIGNALS: dict[str, str] = {
    "manufacturing":  "Manufacturing companies often face production scheduling and quality control bottlenecks as they scale.",
    "logistics":      "Logistics companies typically encounter route optimization and last-mile delivery coordination challenges.",
    "construction":   "Construction firms may struggle with project timeline management and subcontractor coordination at scale.",
    "retail":         "Retail businesses often experience inventory visibility and demand forecasting gaps across multiple locations.",
    "healthcare":     "Healthcare organizations frequently face patient data management and regulatory compliance overhead.",
    "real estate":    "Real estate companies may encounter lead tracking and deal pipeline visibility challenges as portfolios grow.",
    "finance":        "Financial services firms often deal with manual reporting workflows and audit trail management complexity.",
    "education":      "Educational institutions typically experience student engagement tracking and administrative process inefficiencies.",
    "hospitality":    "Hospitality businesses may face occupancy forecasting and staff scheduling coordination challenges.",
    "technology":     "Technology companies often encounter project delivery consistency and cross-team dependency management issues.",
    "food":           "Food and beverage companies typically face supply chain traceability and compliance documentation challenges.",
    "energy":         "Energy sector companies may experience asset maintenance scheduling and regulatory reporting complexity.",
    "telecom":        "Telecom companies often encounter customer churn prediction and service quality monitoring challenges.",
}

# Domain → likely process challenge patterns
_DOMAIN_SIGNALS: dict[str, str] = {
    "erp":            "Companies evaluating or running ERP systems may face data migration complexity and user adoption resistance.",
    "supply chain":   "Supply chain operations often encounter supplier visibility gaps and demand-supply synchronization delays.",
    "hr":             "HR-focused organizations may struggle with talent retention analytics and onboarding process standardization.",
    "crm":            "CRM-dependent businesses often face data quality issues and sales pipeline forecasting inaccuracies.",
    "finance":        "Finance-focused operations typically experience month-end close delays and manual reconciliation overhead.",
    "digital":        "Companies undergoing digital transformation may encounter change management resistance and integration complexity.",
    "operations":     "Operations-heavy businesses often face process standardization gaps and cross-department visibility challenges.",
    "procurement":    "Procurement teams typically experience vendor evaluation inconsistency and purchase approval bottlenecks.",
}


def _derive_rule_signals(
    enriched: EnrichedLead,
    context: BusinessContext,
) -> list[str]:
    """
    Derive factual, observable signals from lead data without LLM.
    Returns a list of short signal strings passed to the LLM prompt.
    """
    signals: list[str] = []

    # Service complexity signal
    svc_count = len(enriched.services_detected)
    if svc_count >= 5:
        signals.append(f"Company offers {svc_count} distinct services — suggests operational complexity.")
    elif svc_count >= 3:
        signals.append(f"Company offers {svc_count} services — moderate operational breadth.")

    # Industry pattern
    industry_key = (enriched.industry or "").lower()
    for key, signal in _INDUSTRY_SIGNALS.items():
        if key in industry_key or any(key in ind.lower() for ind in context.industries):
            signals.append(signal)
            break  # one industry signal is enough

    # Domain pattern
    domain_key = (context.domain or "").lower()
    for key, signal in _DOMAIN_SIGNALS.items():
        if key in domain_key:
            signals.append(signal)
            break

    # B2B scaling signal
    if enriched.business_type.value == "B2B":
        signals.append("B2B company — likely faces process standardization and client delivery consistency challenges as it scales.")

    # Website language signal (Arabic-only sites may have limited digital tooling)
    if enriched.language_of_website == "ar":
        signals.append("Arabic-only website may indicate limited investment in digital infrastructure or international tooling.")

    # Founding year signal (older companies may have legacy system debt)
    if enriched.founding_year and enriched.founding_year < 2010:
        age = 2025 - enriched.founding_year
        signals.append(f"Company has been operating for ~{age} years — may carry legacy process or system debt.")

    return signals[:4]  # cap at 4 signals to keep prompt focused


# ──────────────────────────────────────────────────────────────────────────────
# Main inference function
# ──────────────────────────────────────────────────────────────────────────────

async def infer_pain_points(
    enriched: EnrichedLead,
    evaluated: EvaluatedLead,
    context: BusinessContext,
) -> list[str]:
    """
    Infer 2–3 likely business challenges for this company.

    Flow:
      1. Derive rule-based signals (free, instant)
      2. Call LLM with full context + signals
      3. Parse JSON response safely
      4. Fall back to context.pain_points or [] on any failure

    Returns list[str] — never raises.
    """
    rule_signals = _derive_rule_signals(enriched, context)

    # If we have no useful signals and no summary, skip LLM and return fallback
    if not enriched.summary and not rule_signals:
        logger.info(
            "pain_inference.skipped",
            lead_id=str(enriched.lead_id),
            reason="no_summary_no_signals",
        )
        return list(context.pain_points)

    try:
        prompt = load_prompt("pain_inference").format(
            company_name=enriched.company_name,
            industry=enriched.industry or ", ".join(context.industries),
            domain=context.domain or "N/A",
            summary=enriched.summary or "N/A",
            services=", ".join(enriched.services_detected) if enriched.services_detected else "N/A",
            business_type=enriched.business_type.value,
            service_count=len(enriched.services_detected),
            icp_reasoning=evaluated.llm_reasoning or "N/A",
            context_pain_points=", ".join(context.pain_points) if context.pain_points else "N/A",
            notes=context.notes or "N/A",
            rule_signals="\n".join(f"- {s}" for s in rule_signals) if rule_signals else "None detected.",
        )

        response = await llm_chat(
            model=settings.ollama_model,
            messages=[
                {"role": "system", "content": "You are a JSON-only responder. Output valid JSON and nothing else."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=300,
            temperature=0.3,
        )

        raw = response.choices[0].message.content or "{}"
        raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()

        data = json.loads(raw)
        points = data.get("pain_points", [])

        if not isinstance(points, list) or not points:
            raise ValueError("empty or malformed pain_points list")

        # Sanitise: keep only non-empty strings, cap at 3
        cleaned = [str(p).strip() for p in points if str(p).strip()][:3]

        logger.info(
            "pain_inference.success",
            lead_id=str(enriched.lead_id),
            count=len(cleaned),
        )
        return cleaned

    except json.JSONDecodeError as e:
        logger.warning(
            "pain_inference.json_parse_failed",
            lead_id=str(enriched.lead_id),
            error=str(e),
        )
    except Exception as e:
        logger.warning(
            "pain_inference.failed",
            lead_id=str(enriched.lead_id),
            error=str(e),
        )

    # Fallback: use caller-supplied pain points, or empty list
    fallback = list(context.pain_points)
    logger.info(
        "pain_inference.fallback",
        lead_id=str(enriched.lead_id),
        fallback_count=len(fallback),
    )
    return fallback
