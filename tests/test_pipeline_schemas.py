"""
Unit tests for rule engine and filter service.
Uses new schema field names (location, website, industries, etc.)
No LLM or network calls.
"""

import uuid
import pytest
from datetime import datetime, timezone
from app.schemas import (
    BusinessContext,
    RawLead,
    EnrichedLead,
    LeadStatus,
    FilterReason,
    OutreachLanguage,
    BusinessType,
)
from app.modules.icp.rules import RuleEngine
from app.modules.filter.service import FilterService

PIPELINE_RUN_ID = uuid.uuid4()

SAMPLE_CONTEXT = BusinessContext(
    industries=["manufacturing", "logistics"],
    excluded_categories=["restaurant", "clinic"],
    location="Riyadh",
    pain_points=["operational inefficiency"],
    value_proposition="We help KSA enterprises cut costs by 30% in 90 days.",
)


def _make_enriched(**kwargs) -> EnrichedLead:
    defaults = dict(
        lead_id=uuid.uuid4(),
        trace_id=uuid.uuid4(),
        pipeline_run_id=PIPELINE_RUN_ID,
        source="google_maps",
        discovered_at=datetime.now(timezone.utc),
        company_name="Test Co",
        location="Riyadh",
        enrichment_success=True,
        summary="A test company in Riyadh.",
    )
    defaults.update(kwargs)
    return EnrichedLead(**defaults)


# ─── Rule engine ──────────────────────────────────────────────────────────────

def test_rule_industry_match():
    engine = RuleEngine()
    lead = _make_enriched(
        company_name="Riyadh Manufacturing Co",
        summary="We provide manufacturing solutions across KSA.",
        services_detected=["manufacturing", "supply chain"],
    )
    results = engine.run(lead, SAMPLE_CONTEXT)
    rule = next(r for r in results if r.rule_name == "industry_match")
    assert rule.passed is True


def test_rule_no_website_fails():
    engine = RuleEngine()
    lead = _make_enriched(website=None)
    results = engine.run(lead, SAMPLE_CONTEXT)
    rule = next(r for r in results if r.rule_name == "has_website")
    assert rule.passed is False


def test_rule_ksa_presence():
    engine = RuleEngine()
    lead = _make_enriched(
        location="Riyadh",
        address="King Fahd Road, Riyadh, Saudi Arabia",
    )
    results = engine.run(lead, SAMPLE_CONTEXT)
    rule = next(r for r in results if r.rule_name == "location_presence")
    assert rule.passed is True


# ─── Filter service ───────────────────────────────────────────────────────────

def test_filter_no_website_now_passes():
    """Leads without websites are no longer hard-filtered — ICP scores them lower instead."""
    svc = FilterService()
    lead = _make_enriched(
        enrichment_success=False,
        summary=None,
        website=None,
        address="Riyadh, Saudi Arabia",
    )
    passlist, rejectlist = svc.apply([lead], SAMPLE_CONTEXT)
    # No website leads now pass the filter and get ICP-scored
    assert len(passlist) == 1
    assert len(rejectlist) == 0


def test_filter_rejects_excluded_category():
    svc = FilterService()
    lead = _make_enriched(
        company_name="Al Noor Restaurant",
        website="https://example.com",
        category="restaurant",
        address="Riyadh, Saudi Arabia",
    )
    passlist, rejectlist = svc.apply([lead], SAMPLE_CONTEXT)
    assert len(rejectlist) == 1
    assert rejectlist[0].filter_reason == FilterReason.EXCLUDED_CATEGORY


def test_filter_deduplicates():
    svc = FilterService()
    lead = _make_enriched(
        website="https://example.com",
        address="Riyadh, Saudi Arabia",
    )
    seen = {lead.lead_id}
    passlist, rejectlist = svc.apply([lead], SAMPLE_CONTEXT, seen_ids=seen)
    assert len(passlist) == 0
    assert rejectlist[0].filter_reason == FilterReason.DUPLICATE


def test_filter_passes_valid_lead():
    svc = FilterService()
    lead = _make_enriched(
        company_name="Riyadh Logistics Co",
        location="Riyadh",
        address="King Fahd Road, Riyadh, Saudi Arabia",
        website="https://example.com",
        category="logistics",
    )
    passlist, rejectlist = svc.apply([lead], SAMPLE_CONTEXT)
    assert len(passlist) == 1
    assert len(rejectlist) == 0
