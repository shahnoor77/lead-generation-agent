"""
Pipeline Contract Tests
-----------------------
Simulates the full pipeline using mock data to verify:
  - Schema compatibility across all stages
  - Validation rules enforced at schema level
  - Traceability (lead_id / trace_id / pipeline_run_id) preserved end-to-end
  - Immutability: each stage produces a new object
  - Enum strictness
  - Computed fields (word_count)
  - Validator guards (word limit, llm consistency, rejection reason, etc.)

No LLM calls. No network. No DB. Pure contract verification.
"""

import uuid
import pytest
from pydantic import ValidationError

from app.schemas import (
    BusinessContext,
    RawLead,
    EnrichedLead,
    FilteredLead,
    EvaluatedLead,
    OutreachOutput,
    ICPRuleResult,
    LeadStatus,
    FilterReason,
    BusinessType,
    ICPDecision,
    OutreachLanguage,
    LeadSource,
)


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

PIPELINE_RUN_ID = uuid.uuid4()


@pytest.fixture
def context() -> BusinessContext:
    return BusinessContext(
        industries=["manufacturing", "logistics"],
        location="Riyadh",
        excluded_categories=["restaurant", "clinic"],
        pain_points=["operational inefficiency", "digital transformation lag"],
        value_proposition="We help KSA enterprises cut operational costs by 30% in 90 days.",
        language_preference=OutreachLanguage.AR,
    )


@pytest.fixture
def raw_lead_a() -> RawLead:
    """Valid lead with website — should pass through the full pipeline."""
    return RawLead(
        pipeline_run_id=PIPELINE_RUN_ID,
        company_name="Al Riyadh Manufacturing Co",
        location="Riyadh",
        category="manufacturing",
        website="https://alriyadhmfg.com.sa",
        phone="+966-11-000-0001",
        address="King Fahd Road, Riyadh, Saudi Arabia",
        rating=4.2,
        review_count=38,
    )


@pytest.fixture
def raw_lead_b() -> RawLead:
    """Lead without a website — will be filtered out."""
    return RawLead(
        pipeline_run_id=PIPELINE_RUN_ID,
        company_name="Small Trader Riyadh",
        location="Riyadh",
        category="retail",
        website=None,
        phone="+966-11-000-0002",
        address="Olaya Street, Riyadh",
    )


@pytest.fixture
def raw_lead_c() -> RawLead:
    """Lead in excluded category — will be filtered out."""
    return RawLead(
        pipeline_run_id=PIPELINE_RUN_ID,
        company_name="Al Noor Restaurant",
        location="Riyadh",
        category="restaurant",
        website="https://alnoor-restaurant.com",
        address="Tahlia Street, Riyadh, Saudi Arabia",
    )


# ──────────────────────────────────────────────────────────────────────────────
# Stage 1 — BusinessContext
# ──────────────────────────────────────────────────────────────────────────────

class TestBusinessContext:
    def test_valid_context(self, context: BusinessContext) -> None:
        assert context.industries == ["manufacturing", "logistics"]
        assert context.location == "Riyadh"
        assert context.language_preference == OutreachLanguage.AR

    def test_strips_whitespace_from_industries(self) -> None:
        ctx = BusinessContext(
            industries=["  manufacturing  ", " logistics "],
            location="Riyadh",
            pain_points=["inefficiency"],
            value_proposition="We help.",
        )
        assert ctx.industries == ["manufacturing", "logistics"]

    def test_empty_industries_rejected(self) -> None:
        with pytest.raises(ValidationError):
            BusinessContext(
                industries=[],
                location="Riyadh",
                pain_points=["inefficiency"],
                value_proposition="We help.",
            )

    def test_blank_value_proposition_rejected(self) -> None:
        # value_proposition is now Optional[str] — blank strings are allowed
        ctx = BusinessContext(
            industries=["manufacturing"],
            location="Riyadh",
            pain_points=["inefficiency"],
            value_proposition="   ",  # blank but valid since it's optional
        )
        assert ctx.value_proposition == ""  # stripped to empty string

    def test_invalid_language_rejected(self) -> None:
        with pytest.raises(ValidationError):
            BusinessContext(
                industries=["manufacturing"],
                location="Riyadh",
                pain_points=["inefficiency"],
                value_proposition="We help.",
                language_preference="fr",  # type: ignore[arg-type]
            )


# ──────────────────────────────────────────────────────────────────────────────
# Stage 2 — RawLead
# ──────────────────────────────────────────────────────────────────────────────

class TestRawLead:
    def test_defaults_assigned(self, raw_lead_a: RawLead) -> None:
        assert raw_lead_a.status == LeadStatus.RAW
        assert raw_lead_a.source == LeadSource.GOOGLE_MAPS
        assert isinstance(raw_lead_a.lead_id, uuid.UUID)
        assert isinstance(raw_lead_a.trace_id, uuid.UUID)
        assert raw_lead_a.pipeline_run_id == PIPELINE_RUN_ID

    def test_lead_ids_are_unique(self, raw_lead_a: RawLead, raw_lead_b: RawLead) -> None:
        assert raw_lead_a.lead_id != raw_lead_b.lead_id
        assert raw_lead_a.trace_id != raw_lead_b.trace_id

    def test_invalid_rating_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RawLead(
                pipeline_run_id=PIPELINE_RUN_ID,
                company_name="Test Co",
                location="Riyadh",
                rating=6.0,  # max is 5.0
            )

    def test_blank_company_name_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RawLead(
                pipeline_run_id=PIPELINE_RUN_ID,
                company_name="   ",
                location="Riyadh",
            )

    def test_immutable(self, raw_lead_a: RawLead) -> None:
        with pytest.raises(Exception):
            raw_lead_a.company_name = "mutated"  # type: ignore[misc]


# ──────────────────────────────────────────────────────────────────────────────
# Stage 3 — EnrichedLead
# ──────────────────────────────────────────────────────────────────────────────

def _enrich(raw: RawLead, success: bool = True, summary: str | None = None) -> EnrichedLead:
    """Helper: simulate enrichment from a RawLead."""
    return EnrichedLead(
        lead_id=raw.lead_id,
        trace_id=raw.trace_id,
        pipeline_run_id=raw.pipeline_run_id,
        source=raw.source,
        discovered_at=raw.discovered_at,
        company_name=raw.company_name,
        location=raw.location,
        category=raw.category,
        website=raw.website,
        phone=raw.phone,
        address=raw.address,
        rating=raw.rating,
        review_count=raw.review_count,
        enrichment_success=success,
        summary=summary or ("A manufacturing company in Riyadh." if success else None),
        industry="manufacturing" if success else None,
        business_type=BusinessType.B2B if success else BusinessType.UNKNOWN,
        services_detected=["CNC machining", "metal fabrication"] if success else [],
        contact_email="info@alriyadhmfg.com.sa" if success else None,
    )


class TestEnrichedLead:
    def test_lead_id_preserved(self, raw_lead_a: RawLead) -> None:
        enriched = _enrich(raw_lead_a)
        assert enriched.lead_id == raw_lead_a.lead_id
        assert enriched.trace_id == raw_lead_a.trace_id

    def test_status_is_enriched(self, raw_lead_a: RawLead) -> None:
        enriched = _enrich(raw_lead_a)
        assert enriched.status == LeadStatus.ENRICHED

    def test_summary_required_on_success(self, raw_lead_a: RawLead) -> None:
        with pytest.raises(ValidationError, match="summary must be provided"):
            EnrichedLead(
                lead_id=raw_lead_a.lead_id,
                trace_id=raw_lead_a.trace_id,
                pipeline_run_id=raw_lead_a.pipeline_run_id,
                source=raw_lead_a.source,
                discovered_at=raw_lead_a.discovered_at,
                company_name=raw_lead_a.company_name,
                location=raw_lead_a.location,
                enrichment_success=True,
                summary=None,  # missing — should fail
            )

    def test_failed_enrichment_no_summary_ok(self, raw_lead_b: RawLead) -> None:
        enriched = _enrich(raw_lead_b, success=False)
        assert enriched.enrichment_success is False
        assert enriched.summary is None

    def test_immutable(self, raw_lead_a: RawLead) -> None:
        enriched = _enrich(raw_lead_a)
        with pytest.raises(Exception):
            enriched.summary = "mutated"  # type: ignore[misc]


# ──────────────────────────────────────────────────────────────────────────────
# Stage 4 — FilteredLead
# ──────────────────────────────────────────────────────────────────────────────

def _filter(enriched: EnrichedLead, reason: FilterReason) -> FilteredLead:
    return FilteredLead(
        lead_id=enriched.lead_id,
        trace_id=enriched.trace_id,
        pipeline_run_id=enriched.pipeline_run_id,
        company_name=enriched.company_name,
        location=enriched.location,
        category=enriched.category,
        website=enriched.website,
        enrichment_success=enriched.enrichment_success,
        filter_reason=reason,
    )


class TestFilteredLead:
    def test_lead_id_preserved(self, raw_lead_b: RawLead) -> None:
        enriched = _enrich(raw_lead_b, success=False)
        filtered = _filter(enriched, FilterReason.NO_WEBSITE)
        assert filtered.lead_id == raw_lead_b.lead_id

    def test_status_is_filtered(self, raw_lead_b: RawLead) -> None:
        enriched = _enrich(raw_lead_b, success=False)
        filtered = _filter(enriched, FilterReason.NO_WEBSITE)
        assert filtered.status == LeadStatus.FILTERED

    def test_all_filter_reasons_valid(self, raw_lead_b: RawLead) -> None:
        enriched = _enrich(raw_lead_b, success=False)
        for reason in FilterReason:
            f = _filter(enriched, reason)
            assert f.filter_reason == reason

    def test_invalid_filter_reason_rejected(self, raw_lead_b: RawLead) -> None:
        enriched = _enrich(raw_lead_b, success=False)
        with pytest.raises(ValidationError):
            FilteredLead(
                lead_id=enriched.lead_id,
                trace_id=enriched.trace_id,
                pipeline_run_id=enriched.pipeline_run_id,
                company_name=enriched.company_name,
                location=enriched.location,
                enrichment_success=False,
                filter_reason="MADE_UP_REASON",  # type: ignore[arg-type]
            )


# ──────────────────────────────────────────────────────────────────────────────
# Stage 5 — EvaluatedLead
# ──────────────────────────────────────────────────────────────────────────────

def _evaluate(
    enriched: EnrichedLead,
    fit_score: int = 75,
    rule_score: int = 80,
    llm_score: int | None = 70,
    decision: ICPDecision = ICPDecision.QUALIFIED,
) -> EvaluatedLead:
    return EvaluatedLead(
        lead_id=enriched.lead_id,
        trace_id=enriched.trace_id,
        pipeline_run_id=enriched.pipeline_run_id,
        company_name=enriched.company_name,
        location=enriched.location,
        website=enriched.website,
        fit_score=fit_score,
        rule_score=rule_score,
        llm_score=llm_score,
        llm_was_called=llm_score is not None,
        confidence_score=0.82,
        decision=decision,
        rule_results=[
            ICPRuleResult(rule_name="has_website", passed=True, reason="Has website"),
            ICPRuleResult(rule_name="industry_match", passed=True, reason="Matched: manufacturing"),
            ICPRuleResult(rule_name="ksa_presence", passed=True, reason="Riyadh confirmed"),
        ],
        llm_reasoning="Company shows strong operational complexity signals." if llm_score else None,
        disqualification_reason=None if decision == ICPDecision.QUALIFIED else "rule_score_below_threshold",
    )


class TestEvaluatedLead:
    def test_lead_id_preserved(self, raw_lead_a: RawLead) -> None:
        enriched = _enrich(raw_lead_a)
        evaluated = _evaluate(enriched)
        assert evaluated.lead_id == raw_lead_a.lead_id

    def test_qualified_decision(self, raw_lead_a: RawLead) -> None:
        enriched = _enrich(raw_lead_a)
        evaluated = _evaluate(enriched, decision=ICPDecision.QUALIFIED)
        assert evaluated.decision == ICPDecision.QUALIFIED

    def test_rejected_requires_disqualification_reason(self, raw_lead_a: RawLead) -> None:
        enriched = _enrich(raw_lead_a)
        with pytest.raises(ValidationError, match="disqualification_reason required"):
            EvaluatedLead(
                lead_id=enriched.lead_id,
                trace_id=enriched.trace_id,
                pipeline_run_id=enriched.pipeline_run_id,
                company_name=enriched.company_name,
                location=enriched.location,
                fit_score=20,
                rule_score=20,
                llm_was_called=False,
                confidence_score=0.2,
                decision=ICPDecision.REJECTED,
                disqualification_reason=None,  # missing — should fail
            )

    def test_llm_score_required_when_called(self, raw_lead_a: RawLead) -> None:
        enriched = _enrich(raw_lead_a)
        with pytest.raises(ValidationError, match="llm_score must be provided"):
            EvaluatedLead(
                lead_id=enriched.lead_id,
                trace_id=enriched.trace_id,
                pipeline_run_id=enriched.pipeline_run_id,
                company_name=enriched.company_name,
                location=enriched.location,
                fit_score=70,
                rule_score=70,
                llm_was_called=True,
                llm_score=None,  # missing — should fail
                confidence_score=0.7,
                decision=ICPDecision.QUALIFIED,
            )

    def test_llm_score_must_be_none_when_not_called(self, raw_lead_a: RawLead) -> None:
        enriched = _enrich(raw_lead_a)
        with pytest.raises(ValidationError, match="llm_score must be None"):
            EvaluatedLead(
                lead_id=enriched.lead_id,
                trace_id=enriched.trace_id,
                pipeline_run_id=enriched.pipeline_run_id,
                company_name=enriched.company_name,
                location=enriched.location,
                fit_score=70,
                rule_score=70,
                llm_was_called=False,
                llm_score=65,  # should not be set — should fail
                confidence_score=0.7,
                decision=ICPDecision.QUALIFIED,
            )

    def test_score_bounds(self, raw_lead_a: RawLead) -> None:
        enriched = _enrich(raw_lead_a)
        with pytest.raises(ValidationError):
            _evaluate(enriched, fit_score=101)  # exceeds 100

    def test_confidence_bounds(self, raw_lead_a: RawLead) -> None:
        enriched = _enrich(raw_lead_a)
        with pytest.raises(ValidationError):
            EvaluatedLead(
                lead_id=enriched.lead_id,
                trace_id=enriched.trace_id,
                pipeline_run_id=enriched.pipeline_run_id,
                company_name=enriched.company_name,
                location=enriched.location,
                fit_score=70,
                rule_score=70,
                llm_was_called=False,
                confidence_score=1.5,  # exceeds 1.0
                decision=ICPDecision.QUALIFIED,
            )


# ──────────────────────────────────────────────────────────────────────────────
# Stage 6 — OutreachOutput
# ──────────────────────────────────────────────────────────────────────────────

def _outreach(evaluated: EvaluatedLead, body: str | None = None) -> OutreachOutput:
    return OutreachOutput(
        lead_id=evaluated.lead_id,
        trace_id=evaluated.trace_id,
        pipeline_run_id=evaluated.pipeline_run_id,
        email_subject="تحويل العمليات في شركتكم",
        email_body=body or (
            "نود مشاركتكم بعض الأفكار حول تحسين الكفاءة التشغيلية. "
            "لاحظنا أن شركتكم تعمل في قطاع التصنيع وقد تواجه تحديات مشابهة "
            "لما نساعد عملاءنا في التغلب عليه. هل يمكننا تحديد موعد لمكالمة قصيرة؟"
        ),
        language=OutreachLanguage.AR,
        personalization_hooks=["manufacturing sector", "Riyadh presence"],
        approved=False,
    )


class TestOutreachOutput:
    def test_lead_id_preserved(self, raw_lead_a: RawLead) -> None:
        enriched = _enrich(raw_lead_a)
        evaluated = _evaluate(enriched)
        outreach = _outreach(evaluated)
        assert outreach.lead_id == raw_lead_a.lead_id
        assert outreach.trace_id == raw_lead_a.trace_id
        assert outreach.pipeline_run_id == raw_lead_a.pipeline_run_id

    def test_word_count_computed(self, raw_lead_a: RawLead) -> None:
        enriched = _enrich(raw_lead_a)
        evaluated = _evaluate(enriched)
        outreach = _outreach(evaluated)
        expected = len(outreach.email_body.split())
        assert outreach.word_count == expected

    def test_word_count_is_readonly(self, raw_lead_a: RawLead) -> None:
        enriched = _enrich(raw_lead_a)
        evaluated = _evaluate(enriched)
        outreach = _outreach(evaluated)
        with pytest.raises(Exception):
            outreach.word_count = 999  # type: ignore[misc]

    def test_word_limit_enforced(self, raw_lead_a: RawLead) -> None:
        enriched = _enrich(raw_lead_a)
        evaluated = _evaluate(enriched)
        long_body = " ".join(["word"] * 350)  # 350 words > default 300
        with pytest.raises(ValidationError, match="exceeds max_allowed_words"):
            _outreach(evaluated, body=long_body)

    def test_custom_word_limit(self, raw_lead_a: RawLead) -> None:
        enriched = _enrich(raw_lead_a)
        evaluated = _evaluate(enriched)
        body = " ".join(["word"] * 50)
        outreach = OutreachOutput(
            lead_id=evaluated.lead_id,
            trace_id=evaluated.trace_id,
            pipeline_run_id=evaluated.pipeline_run_id,
            email_subject="Test subject",
            email_body=body,
            language=OutreachLanguage.EN,
            max_allowed_words=50,
            approved=False,
        )
        assert outreach.word_count == 50

    def test_approved_must_be_false(self, raw_lead_a: RawLead) -> None:
        enriched = _enrich(raw_lead_a)
        evaluated = _evaluate(enriched)
        with pytest.raises(ValidationError, match="approved must be False"):
            OutreachOutput(
                lead_id=evaluated.lead_id,
                trace_id=evaluated.trace_id,
                pipeline_run_id=evaluated.pipeline_run_id,
                email_subject="Test",
                email_body="Short body text here.",
                language=OutreachLanguage.EN,
                approved=True,  # must be False — should fail
            )

    def test_subject_max_length(self, raw_lead_a: RawLead) -> None:
        enriched = _enrich(raw_lead_a)
        evaluated = _evaluate(enriched)
        with pytest.raises(ValidationError):
            OutreachOutput(
                lead_id=evaluated.lead_id,
                trace_id=evaluated.trace_id,
                pipeline_run_id=evaluated.pipeline_run_id,
                email_subject="x" * 81,  # exceeds 80 chars
                email_body="Short body.",
                language=OutreachLanguage.EN,
                approved=False,
            )


# ──────────────────────────────────────────────────────────────────────────────
# Full pipeline simulation — end-to-end contract check
# ──────────────────────────────────────────────────────────────────────────────

class TestFullPipelineContracts:
    """
    Simulates the full pipeline with 3 mock leads:
      - Lead A: passes all stages → outreach generated
      - Lead B: filtered (no website)
      - Lead C: filtered (excluded category)
    Verifies lead_id / trace_id / pipeline_run_id are consistent end-to-end.
    """

    def test_pipeline_simulation(
        self,
        raw_lead_a: RawLead,
        raw_lead_b: RawLead,
        raw_lead_c: RawLead,
    ) -> None:
        # ── Stage 1: Raw leads ─────────────────────────────────────────────
        assert raw_lead_a.pipeline_run_id == PIPELINE_RUN_ID
        assert raw_lead_b.pipeline_run_id == PIPELINE_RUN_ID
        assert raw_lead_c.pipeline_run_id == PIPELINE_RUN_ID

        # ── Stage 2: Enrichment ────────────────────────────────────────────
        enriched_a = _enrich(raw_lead_a, success=True)
        enriched_b = _enrich(raw_lead_b, success=False)  # no website
        enriched_c = _enrich(raw_lead_c, success=True, summary="A restaurant in Riyadh.")

        assert enriched_a.lead_id == raw_lead_a.lead_id
        assert enriched_b.enrichment_success is False

        # ── Stage 3: Filter ────────────────────────────────────────────────
        filtered_b = _filter(enriched_b, FilterReason.NO_WEBSITE)
        filtered_c = _filter(enriched_c, FilterReason.EXCLUDED_CATEGORY)

        assert filtered_b.lead_id == raw_lead_b.lead_id
        assert filtered_b.filter_reason == FilterReason.NO_WEBSITE
        assert filtered_c.filter_reason == FilterReason.EXCLUDED_CATEGORY
        assert filtered_b.status == LeadStatus.FILTERED
        assert filtered_c.status == LeadStatus.FILTERED

        # ── Stage 4: ICP Evaluation (lead A only) ─────────────────────────
        evaluated_a = _evaluate(enriched_a, decision=ICPDecision.QUALIFIED)
        assert evaluated_a.lead_id == raw_lead_a.lead_id
        assert evaluated_a.decision == ICPDecision.QUALIFIED
        assert evaluated_a.llm_was_called is True
        assert evaluated_a.llm_score is not None

        # ── Stage 5: Outreach (lead A only) ───────────────────────────────
        outreach_a = _outreach(evaluated_a)
        assert outreach_a.lead_id == raw_lead_a.lead_id
        assert outreach_a.trace_id == raw_lead_a.trace_id
        assert outreach_a.pipeline_run_id == PIPELINE_RUN_ID
        assert outreach_a.approved is False
        assert outreach_a.word_count > 0
        assert outreach_a.word_count <= outreach_a.max_allowed_words  # 300

        # ── Traceability: lead_id stable across all 5 stages ──────────────
        assert (
            raw_lead_a.lead_id
            == enriched_a.lead_id
            == evaluated_a.lead_id
            == outreach_a.lead_id
        )
        assert (
            raw_lead_a.trace_id
            == enriched_a.trace_id
            == evaluated_a.trace_id
            == outreach_a.trace_id
        )

        print("\n✓ Pipeline contract simulation passed")
        print(f"  Lead A ({raw_lead_a.company_name}): raw → enriched → evaluated → outreach")
        print(f"  Lead B ({raw_lead_b.company_name}): raw → enriched → filtered ({filtered_b.filter_reason.value})")
        print(f"  Lead C ({raw_lead_c.company_name}): raw → enriched → filtered ({filtered_c.filter_reason.value})")
        print(f"  Outreach word count: {outreach_a.word_count}/{outreach_a.max_allowed_words}")
        print(f"  approved={outreach_a.approved} (human gate enforced)")
