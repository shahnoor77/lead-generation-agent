"""
Filter Layer
------------
Sits between Enrichment and ICP Evaluation.
Responsibility: Discard leads that are structurally unfit BEFORE spending LLM tokens.

DOES:
  - Check data quality (no website, enrichment failed)
  - Detect duplicates within a pipeline run
  - Reject excluded categories defined in BusinessContext
  - Confirm KSA geographic presence

MUST NOT:
  - Apply business/ICP logic (that belongs to ICP module)
  - Make LLM calls
  - Modify lead data — only creates a new FilteredLead (immutable schemas)

Input:  list[EnrichedLead] + BusinessContext + seen_ids (dedup set)
Output: tuple[list[EnrichedLead], list[FilteredLead]]
        — passlist (proceed to ICP) and rejectlist (stored, not evaluated)
"""

import uuid
from datetime import datetime, timezone

from app.schemas import (
    BusinessContext,
    EnrichedLead,
    FilteredLead,
    FilterReason,
    LeadStatus,
)
from app.modules.qualification.buyer_seller_classifier import (
    classify_rule_based,
    BuyerSellerLabel,
)
from app.core.logging import get_logger

logger = get_logger(__name__)

KSA_LOCATION_SIGNALS = {
    "riyadh", "jeddah", "dammam", "mecca", "medina", "khobar",
    "tabuk", "abha", "saudi", "ksa", "الرياض", "جدة", "المملكة",
}


def _location_signals(context: BusinessContext) -> set[str]:
    """
    Build a set of location signals from what the user actually provided.
    Falls back to the KSA defaults only when no country is given and
    the location itself looks like a KSA city.
    """
    signals: set[str] = set()

    # Always include the user-supplied location and its parts
    for part in context.location.lower().split():
        if len(part) > 2:
            signals.add(part)

    # Include country if provided
    if context.country:
        for part in context.country.lower().split():
            if len(part) > 2:
                signals.add(part)

    # Include area if provided
    if context.area:
        for part in context.area.lower().split():
            if len(part) > 2:
                signals.add(part)

    # If nothing useful was derived, fall back to KSA defaults
    # (handles legacy calls that don't pass country)
    if not signals:
        signals = KSA_LOCATION_SIGNALS.copy()

    return signals


class FilterService:
    def apply(
        self,
        leads: list[EnrichedLead],
        context: BusinessContext,
        seen_ids: set[uuid.UUID] | None = None,
        icp_settings=None,  # ICPSettings | None
    ) -> tuple[list[EnrichedLead], list[FilteredLead]]:
        """
        Returns (passlist, rejectlist).
        seen_ids is mutated in-place to track duplicates across calls.
        icp_settings: user's ICPSettings — used for require_website / require_contact.
        """
        if seen_ids is None:
            seen_ids = set()

        require_website = icp_settings.require_website if icp_settings else False
        require_contact = icp_settings.require_contact if icp_settings else False

        passlist: list[EnrichedLead] = []
        rejectlist: list[FilteredLead] = []

        for lead in leads:
            reason = self._check(lead, context, seen_ids,
                                 require_website=require_website,
                                 require_contact=require_contact)
            if reason is None:
                seen_ids.add(lead.lead_id)
                passlist.append(lead)
            else:
                rejected = FilteredLead(
                    lead_id=lead.lead_id,
                    trace_id=lead.trace_id,
                    pipeline_run_id=lead.pipeline_run_id,
                    status=LeadStatus.FILTERED,
                    company_name=lead.company_name,
                    location=lead.location,
                    category=lead.category,
                    website=lead.website,
                    enrichment_success=lead.enrichment_success,
                    filter_reason=reason,
                )
                rejectlist.append(rejected)
                logger.info(
                    "filter.rejected",
                    lead_id=str(lead.lead_id),
                    trace_id=str(lead.trace_id),
                    reason=reason.value,
                    company=lead.company_name,
                )

        logger.info("filter.complete", passed=len(passlist), rejected=len(rejectlist))
        return passlist, rejectlist

    def _check(
        self,
        lead: EnrichedLead,
        context: BusinessContext,
        seen_ids: set[uuid.UUID],
        require_website: bool = False,
        require_contact: bool = False,
    ) -> FilterReason | None:
        # 1. Duplicate within this run
        if lead.lead_id in seen_ids:
            return FilterReason.DUPLICATE

        # 2. Enrichment hard-failed (scrape crashed — not just missing website)
        if not lead.enrichment_success and lead.enrichment_error and \
                not lead.enrichment_error.startswith("no_website"):
            return FilterReason.ENRICHMENT_FAILED

        # 3. Require website (user setting)
        if require_website and not lead.website:
            return FilterReason.NO_WEBSITE

        # 4. Require contact info (user setting)
        if require_contact and not (lead.contact_email or lead.phone):
            return FilterReason.NO_CONTACT

        # 5. Excluded category (caller-defined hard exclusions)
        if context.excluded_categories and lead.category:
            cat_lower = lead.category.lower()
            if any(excl.lower() in cat_lower for excl in context.excluded_categories):
                return FilterReason.EXCLUDED_CATEGORY

        # 6. Buyer/Seller classification — only filter CLEAR sellers (high confidence)
        if context.our_services:
            bs_result = classify_rule_based(lead, context)
            if bs_result.classification == BuyerSellerLabel.SELLER and bs_result.seller_score >= 60:
                logger.info(
                    "filter.competitor_seller",
                    lead_id=str(lead.lead_id),
                    seller_score=bs_result.seller_score,
                    signals=bs_result.seller_signals[:3],
                    company=lead.company_name,
                )
                return FilterReason.COMPETITOR_SELLER

        # 7. Location presence check
        signals = _location_signals(context)
        location_text = " ".join([
            lead.location or "",
            lead.address or "",
        ]).lower()
        if not any(sig in location_text for sig in signals):
            return FilterReason.OUTSIDE_TARGET_REGION

        return None  # passes all checks
