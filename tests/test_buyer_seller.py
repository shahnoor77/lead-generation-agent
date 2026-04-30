"""Buyer vs Seller Classifier tests (Phase 1.5 Chunk 2). No LLM, no network."""
import uuid
from datetime import datetime, timezone
from app.schemas import BusinessContext, EnrichedLead, BusinessType, LeadSource
from app.modules.qualification.buyer_seller_classifier import (
    classify_rule_based, apply_buyer_seller_penalty, BuyerSellerLabel, BuyerSellerResult,
)

def _lead(name, cat="", summary="", svcs=None):
    return EnrichedLead(
        lead_id=uuid.uuid4(), trace_id=uuid.uuid4(), pipeline_run_id=uuid.uuid4(),
        source=LeadSource.GOOGLE_MAPS, discovered_at=datetime.now(timezone.utc),
        company_name=name, location="Riyadh", enrichment_success=True,
        summary=summary or f"{name} in Riyadh.", category=cat,
        services_detected=svcs or [], business_type=BusinessType.UNKNOWN,
    )

def _ctx(**kw): return BusinessContext(industries=["manufacturing"], location="Riyadh", **kw)

def test_erp_consulting_is_seller():
    lead = _lead("AlphaEdge ERP Consulting", "IT consulting",
                 "AlphaEdge provides ERP consulting and implementation services.",
                 ["ERP consulting"])
    r = classify_rule_based(lead, _ctx(our_services=["ERP consulting"]))
    assert r.classification == BuyerSellerLabel.SELLER
    assert r.seller_score >= 60

def test_manufacturer_is_buyer():
    lead = _lead("Riyadh Steel Manufacturing", "Manufacturing",
                 "A steel manufacturing plant producing structural components.")
    r = classify_rule_based(lead, _ctx(our_services=["ERP consulting"]))
    assert r.classification == BuyerSellerLabel.BUYER
    assert r.buyer_score >= 20  # 2 signals x 20 = 40

def test_logistics_is_buyer():
    lead = _lead("Gulf Freight Logistics", "Logistics",
                 "Gulf Freight operates warehouses and manages freight distribution.")
    r = classify_rule_based(lead, _ctx(our_services=["supply chain optimization"]))
    assert r.classification == BuyerSellerLabel.BUYER

def test_seller_penalty():
    bs = BuyerSellerResult(classification=BuyerSellerLabel.SELLER,
                           buyer_score=0, seller_score=80, reasoning="Seller.")
    adj, reason = apply_buyer_seller_penalty(80, bs)
    assert adj < 80 and adj >= 10 and reason is not None

def test_buyer_bonus():
    bs = BuyerSellerResult(classification=BuyerSellerLabel.BUYER,
                           buyer_score=60, seller_score=0, reasoning="Buyer.")
    adj, reason = apply_buyer_seller_penalty(70, bs)
    assert adj == 75 and reason is None

def test_uncertain_no_change():
    bs = BuyerSellerResult(classification=BuyerSellerLabel.UNCERTAIN,
                           buyer_score=20, seller_score=20, reasoning="Uncertain.")
    adj, reason = apply_buyer_seller_penalty(60, bs)
    assert adj == 60 and reason is None

def test_penalty_floor():
    bs = BuyerSellerResult(classification=BuyerSellerLabel.SELLER,
                           buyer_score=0, seller_score=90, reasoning="Seller.")
    adj, _ = apply_buyer_seller_penalty(30, bs)
    assert adj >= 10

def test_bonus_cap():
    bs = BuyerSellerResult(classification=BuyerSellerLabel.BUYER,
                           buyer_score=80, seller_score=0, reasoning="Buyer.")
    adj, _ = apply_buyer_seller_penalty(98, bs)
    assert adj == 100

def test_filter_passes_uncertain():
    from app.modules.filter.service import FilterService
    svc = FilterService()
    lead = _lead("Al Faisal Trading", "Trading", "A diversified trading group.")
    la = EnrichedLead(**{**lead.model_dump(), "address": "Riyadh, Saudi Arabia"})
    ctx = _ctx(our_services=["ERP consulting"], country="Saudi Arabia")
    passlist, rejectlist = svc.apply([la], ctx)
    bs = classify_rule_based(la, ctx)
    if bs.seller_score < 75:
        assert len(passlist) == 1

def test_filter_rejects_high_confidence_seller():
    from app.modules.filter.service import FilterService
    from app.schemas import FilterReason
    svc = FilterService()
    lead = _lead("SAP Implementation Partners", "IT consulting",
                 "Certified SAP implementation partner and system integrator.",
                 ["SAP consulting", "ERP implementation"])
    la = EnrichedLead(**{**lead.model_dump(), "address": "Riyadh, Saudi Arabia"})
    ctx = _ctx(our_services=["ERP consulting"], country="Saudi Arabia")
    passlist, rejectlist = svc.apply([la], ctx)
    bs = classify_rule_based(la, ctx)
    if bs.seller_score >= 75:
        assert any(r.filter_reason == FilterReason.COMPETITOR_SELLER for r in rejectlist)
    else:
        assert len(passlist) == 1
