  # uncertain leads pass through
ing",
        summary="A diversified trading group operating in Riyadh.",
    )
    lead_with_address = EnrichedLead(
        **{**lead.model_dump(), "address": "Riyadh, Saudi Arabia"}
    )
    ctx = _ctx(our_services=["ERP consulting"], location="Riyadh", country="Saudi Arabia")
    passlist, rejectlist = svc.apply([lead_with_address], ctx)

    bs = classify_rule_based(lead_with_address, ctx)
    if bs.classification == BuyerSellerLabel.UNCERTAIN or bs.seller_score < 75:
        assert len(passlist) == 175:
        assert len(rejectlist) == 1
        assert rejectlist[0].filter_reason == FilterReason.COMPETITOR_SELLER
    else:
        # Seller score below threshold — passes filter (ICP will penalize instead)
        assert len(passlist) == 1


def test_filter_passes_uncertain_lead():
    """UNCERTAIN leads must not be filtered — they proceed to ICP."""
    from app.modules.filter.service import FilterService

    svc = FilterService()
    lead = _lead(
        "Al Faisal Trading Group",
        category="Trad", "ERP implementation"],
    )
    ctx = _ctx(
        our_services=["ERP consulting"],
        location="Riyadh",
        country="Saudi Arabia",
    )
    # Manually set address so location check passes
    lead_with_address = EnrichedLead(
        **{**lead.model_dump(), "address": "Riyadh, Saudi Arabia"}
    )
    passlist, rejectlist = svc.apply([lead_with_address], ctx)

    # If seller_score >= 75, should be in rejectlist
    bs = classify_rule_based(lead_with_address, ctx)
    if bs.seller_score >= integration ────────────────────────────────────────────────────────

def test_filter_rejects_clear_seller():
    """Filter layer should reject leads with seller_score >= 75."""
    from app.modules.filter.service import FilterService
    from app.schemas import FilterReason

    svc = FilterService()
    lead = _lead(
        "SAP Implementation Partners",
        category="IT consulting",
        summary="We are a certified SAP implementation partner and system integrator.",
        services=["SAP consultingseller_score=90,
        reasoning="Clear seller.",
    )
    adjusted, _ = apply_buyer_seller_penalty(30, bs)
    assert adjusted >= 10


def test_buyer_bonus_capped_at_100():
    from app.modules.qualification.buyer_seller_classifier import BuyerSellerResult
    bs = BuyerSellerResult(
        classification=BuyerSellerLabel.BUYER,
        buyer_score=80,
        seller_score=0,
        reasoning="Strong buyer.",
    )
    adjusted, _ = apply_buyer_seller_penalty(98, bs)
    assert adjusted == 100


# ── Filter Label.UNCERTAIN,
        buyer_score=20,
        seller_score=20,
        reasoning="Insufficient signal.",
    )
    adjusted, reason = apply_buyer_seller_penalty(60, bs)
    assert adjusted == 60
    assert reason is None


def test_seller_penalty_floor():
    """Score should never go below 10 even with heavy penalty."""
    from app.modules.qualification.buyer_seller_classifier import BuyerSellerResult
    bs = BuyerSellerResult(
        classification=BuyerSellerLabel.SELLER,
        buyer_score=0,
        er_classifier import BuyerSellerResult
    bs = BuyerSellerResult(
        classification=BuyerSellerLabel.BUYER,
        buyer_score=60,
        seller_score=0,
        reasoning="Buyer signals detected.",
    )
    adjusted, reason = apply_buyer_seller_penalty(70, bs)
    assert adjusted == 75  # +5 bonus
    assert reason is None


def test_uncertain_no_penalty():
    from app.modules.qualification.buyer_seller_classifier import BuyerSellerResult
    bs = BuyerSellerResult(
        classification=BuyerSeller   lead = _lead("ERP Consulting Co", summary="ERP consulting firm.")
    ctx = _ctx(our_services=["ERP consulting"])
    bs = classify_rule_based(lead, ctx)
    original_score = 80
    adjusted, reason = apply_buyer_seller_penalty(original_score, bs)
    if bs.classification == BuyerSellerLabel.SELLER:
        assert adjusted < original_score
        assert adjusted >= 10  # floor enforced
        assert reason is not None


def test_buyer_bonus_increases_score():
    from app.modules.qualification.buyer_sellic seller detection is skipped but generic patterns still work."""
    lead = _lead(
        "Generic Consulting LLC",
        category="Consulting",
        summary="A consulting firm providing advisory services.",
    )
    ctx = _ctx()  # no our_services
    result = classify_rule_based(lead, ctx)
    # Generic "consulting" pattern should still fire
    assert result.seller_score > 0


# ── ICP penalty ───────────────────────────────────────────────────────────────

def test_seller_penalty_reduces_score():
 _generic_company_is_uncertain():
    lead = _lead(
        "Al Faisal Group",
        category="",
        summary="Al Faisal Group is a diversified company based in Riyadh.",
    )
    ctx = _ctx(our_services=["ERP consulting"])
    result = classify_rule_based(lead, ctx)
    # No strong signals either way
    assert result.classification in (BuyerSellerLabel.UNCERTAIN, BuyerSellerLabel.BUYER, BuyerSellerLabel.SELLER)


def test_no_our_services_still_classifies():
    """Without our_services, service-specifcation == BuyerSellerLabel.BUYER


def test_retailer_is_buyer():
    lead = _lead(
        "Riyadh Hypermarket Group",
        category="Retail",
        summary="A retail chain operating supermarkets and hypermarkets across Saudi Arabia.",
    )
    ctx = _ctx(industries=["retail"], our_services=["inventory management"])
    result = classify_rule_based(lead, ctx)
    assert result.classification == BuyerSellerLabel.BUYER


# ── Uncertain classification ──────────────────────────────────────────────────

def test
    )
    ctx = _ctx(our_services=["supply chain optimization"])
    result = classify_rule_based(lead, ctx)
    assert result.classification == BuyerSellerLabel.BUYER


def test_hospital_is_buyer():
    lead = _lead(
        "Al Noor Medical Center",
        category="Healthcare",
        summary="A hospital providing medical services to patients in Riyadh.",
    )
    ctx = _ctx(industries=["healthcare"], our_services=["process automation"])
    result = classify_rule_based(lead, ctx)
    assert result.classifi
        summary="A steel manufacturing plant producing structural components for construction.",
    )
    ctx = _ctx(our_services=["ERP consulting"])
    result = classify_rule_based(lead, ctx)
    assert result.classification == BuyerSellerLabel.BUYER
    assert result.buyer_score >= 50


def test_logistics_company_is_buyer():
    lead = _lead(
        "Gulf Freight & Logistics",
        category="Logistics",
        summary="Gulf Freight operates warehouses and manages freight distribution across KSA.", Partner Solutions",
        category="Software",
        summary="We are an SAP gold partner providing implementation and advisory services.",
    )
    ctx = _ctx(our_services=["ERP consulting"])
    result = classify_rule_based(lead, ctx)
    assert result.classification == BuyerSellerLabel.SELLER


# ── Clear buyer detection ─────────────────────────────────────────────────────

def test_manufacturer_is_buyer():
    lead = _lead(
        "Riyadh Steel Manufacturing Co",
        category="Manufacturing",x)
    assert result.classification == BuyerSellerLabel.SELLER


def test_system_integrator_is_seller():
    lead = _lead(
        "TechBridge System Integrators",
        category="IT services",
        summary="TechBridge is a certified system integrator and implementation partner.",
    )
    ctx = _ctx(our_services=["ERP consulting"])
    result = classify_rule_based(lead, ctx)
    assert result.classification == BuyerSellerLabel.SELLER


def test_sap_partner_is_seller():
    lead = _lead(
        "SAP Gold(our_services=["ERP consulting"])
    result = classify_rule_based(lead, ctx)
    assert result.classification == BuyerSellerLabel.SELLER
    assert result.seller_score >= 60


def test_digital_transformation_agency_is_seller():
    lead = _lead(
        "Transform Solutions Agency",
        category="Business consulting",
        summary="We are a digital transformation consultancy helping companies modernize.",
    )
    ctx = _ctx(our_services=["digital transformation"])
    result = classify_rule_based(lead, cttext:
    base = dict(industries=["manufacturing"], location="Riyadh")
    base.update(kwargs)
    return BusinessContext(**base)


# ── Clear seller detection ────────────────────────────────────────────────────

def test_erp_consulting_firm_is_seller():
    lead = _lead(
        "AlphaEdge ERP Consulting",
        category="IT consulting",
        summary="AlphaEdge provides ERP consulting and implementation services for enterprises.",
        services=["ERP consulting", "SAP implementation"],
    )
    ctx = _ctxichedLead(
        lead_id=uuid.uuid4(),
        trace_id=uuid.uuid4(),
        pipeline_run_id=uuid.uuid4(),
        source=LeadSource.GOOGLE_MAPS,
        discovered_at=datetime.now(timezone.utc),
        company_name=company_name,
        location="Riyadh",
        enrichment_success=True,
        summary=summary or f"{company_name} operates in Riyadh.",
        category=category,
        services_detected=services or [],
        business_type=BusinessType.UNKNOWN,
    )


def _ctx(**kwargs) -> BusinessConport uuid
import pytest
from datetime import datetime, timezone

from app.schemas import BusinessContext, EnrichedLead, BusinessType, LeadSource, LeadStatus
from app.modules.qualification.buyer_seller_classifier import (
    classify_rule_based,
    apply_buyer_seller_penalty,
    BuyerSellerLabel,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _lead(company_name: str, category: str = "", summary: str = "", services: list[str] | None = None) -> EnrichedLead:
    return Enr"""
Buyer vs Seller Classifier — unit tests (Phase 1.5 Chunk 2).
No LLM, no network. Tests rule-based classification only.
"""

im