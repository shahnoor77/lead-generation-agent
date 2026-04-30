"""
Operational Visibility Layer — unit tests (Chunk 3).
No DB, no network. Tests schema construction and response shapes only.
"""

import pytest
from datetime import datetime
from app.schemas.operations import (
    RunStatusSummary,
    PipelineRunSummary,
    LeadSummary,
    LeadCompanyInfo,
    LeadIntelligence,
    GeneratedDraftView,
    LeadDetailResponse,
)
from app.schemas.lifecycle import LeadStatusHistoryEntry, LeadLifecycleStatus


def _now() -> datetime:
    return datetime.utcnow()


# ── RunStatusSummary ──────────────────────────────────────────────────────────

def test_run_status_summary_defaults_to_zero():
    s = RunStatusSummary()
    assert s.total_discovered == 0
    assert s.total_qualified == 0
    assert s.total_meetings == 0
    assert s.total_won == 0


def test_run_status_summary_accepts_counts():
    s = RunStatusSummary(total_discovered=10, total_qualified=7, total_contacted=3)
    assert s.total_discovered == 10
    assert s.total_qualified == 7
    assert s.total_contacted == 3


# ── PipelineRunSummary ────────────────────────────────────────────────────────

def test_pipeline_run_summary_builds():
    r = PipelineRunSummary(
        run_id="abc-123",
        industries="manufacturing, logistics",
        domain="business transformation",
        location="Riyadh",
        country="Saudi Arabia",
        started_at=_now(),
        completed_at=_now(),
        total_discovered=20,
        total_enriched=20,
        total_evaluated=15,
        total_outreach_drafts=12,
        status_summary=RunStatusSummary(total_qualified=15, total_contacted=3),
    )
    assert r.run_id == "abc-123"
    assert r.status_summary.total_qualified == 15
    assert r.total_outreach_drafts == 12


def test_pipeline_run_summary_optional_fields():
    r = PipelineRunSummary(
        run_id="xyz",
        industries="retail",
        domain=None,
        location="Jeddah",
        country=None,
        started_at=_now(),
        completed_at=None,
        total_discovered=5,
        total_enriched=5,
        total_evaluated=3,
        total_outreach_drafts=2,
        status_summary=RunStatusSummary(),
    )
    assert r.domain is None
    assert r.completed_at is None


# ── LeadSummary ───────────────────────────────────────────────────────────────

def test_lead_summary_builds():
    s = LeadSummary(
        lead_id="lead-1",
        company_name="ACME Logistics",
        website="https://acme.sa",
        location="Riyadh",
        fit_score=82,
        decision="QUALIFIED",
        current_status="OUTREACH_DRAFTED",
        approval_status="PENDING_REVIEW",
        discovered_at=_now(),
    )
    assert s.fit_score == 82
    assert s.decision == "QUALIFIED"
    assert s.current_status == "OUTREACH_DRAFTED"


def test_lead_summary_optional_status():
    s = LeadSummary(
        lead_id="lead-2",
        company_name="No Status Co",
        website=None,
        location="Dammam",
        fit_score=40,
        decision="REJECTED",
        current_status=None,
        approval_status=None,
        discovered_at=_now(),
    )
    assert s.current_status is None
    assert s.approval_status is None


# ── LeadDetailResponse ────────────────────────────────────────────────────────

def test_lead_detail_builds_with_no_drafts():
    detail = LeadDetailResponse(
        lead_id="lead-3",
        pipeline_run_id="run-1",
        company=LeadCompanyInfo(
            company_name="Test Co",
            website="https://test.sa",
            location="Riyadh",
            address="King Fahd Road",
            phone="+966500000000",
            category="logistics",
            rating=4.2,
            review_count=38,
        ),
        intelligence=LeadIntelligence(
            enrichment_summary="Test Co provides logistics services.",
            inferred_pain_points=["Coordination delays", "Manual tracking"],
            icp_reasoning="Strong match on logistics domain.",
            rule_score=80,
            llm_score=85,
            fit_score=82,
            decision="QUALIFIED",
        ),
        generated_draft=None,
        final_draft=None,
        current_status="OUTREACH_DRAFTED",
        status_history=[],
    )
    assert detail.lead_id == "lead-3"
    assert detail.generated_draft is None
    assert detail.final_draft is None
    assert detail.intelligence.fit_score == 82


def test_lead_detail_includes_status_history():
    history = [
        LeadStatusHistoryEntry(
            status=LeadLifecycleStatus.DISCOVERED,
            changed_at=_now(),
            changed_by="pipeline",
            notes=None,
        ),
        LeadStatusHistoryEntry(
            status=LeadLifecycleStatus.QUALIFIED,
            changed_at=_now(),
            changed_by="pipeline",
            notes=None,
        ),
    ]
    detail = LeadDetailResponse(
        lead_id="lead-4",
        pipeline_run_id="run-1",
        company=LeadCompanyInfo(
            company_name="History Co",
            website=None,
            location="Riyadh",
            address=None, phone=None, category=None, rating=None, review_count=None,
        ),
        intelligence=LeadIntelligence(
            enrichment_summary=None,
            inferred_pain_points=[],
            icp_reasoning=None,
            rule_score=60,
            llm_score=None,
            fit_score=60,
            decision="QUALIFIED",
        ),
        generated_draft=None,
        final_draft=None,
        current_status="QUALIFIED",
        status_history=history,
    )
    assert len(detail.status_history) == 2
    assert detail.status_history[0].status == LeadLifecycleStatus.DISCOVERED
    assert detail.status_history[1].status == LeadLifecycleStatus.QUALIFIED


def test_generated_draft_view_builds():
    d = GeneratedDraftView(
        subject="Improving logistics efficiency",
        body="Dear Mr. Ahmed...",
        language="EN",
        word_count=120,
        generated_at=_now(),
    )
    assert d.word_count == 120
    assert d.language == "EN"
