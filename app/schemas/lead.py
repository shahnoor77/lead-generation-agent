"""
Data contracts for the KSA B2B Lead Generation pipeline.

Flow:
  BusinessContext → RawLead → EnrichedLead → FilteredLead → EvaluatedLead → OutreachOutput

Design principles:
  - Immutable: model_config frozen=True on all stage schemas — no in-place mutation
  - Traceable: lead_id + trace_id (UUID) on every stage schema; pipeline_run_id on entry/exit
  - Validated: constraints enforced at schema level, not in business logic
  - Strict enums: no bare strings where a finite set of values is known
  - No business logic: schemas define structure and validation only
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Optional

from pydantic import (
    UUID4,
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    computed_field,
    field_validator,
    model_validator,
)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _new_uuid() -> uuid.UUID:
    return uuid.uuid4()


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


# Reusable annotated types
UnitFloat = Annotated[float, Field(ge=0.0, le=1.0)]
Score100  = Annotated[int,   Field(ge=0, le=100)]
NonEmptyStr = Annotated[str, Field(min_length=1)]


# ──────────────────────────────────────────────────────────────────────────────
# Enums
# ──────────────────────────────────────────────────────────────────────────────

class LeadStatus(str, Enum):
    """
    Lifecycle states. A lead moves forward only — never backward.
    'filtered' and 'rejected' are terminal discard states.
    """
    RAW            = "raw"
    ENRICHED       = "enriched"
    FILTERED       = "filtered"        # discarded by Filter Layer (pre-ICP)
    EVALUATED      = "evaluated"       # ICP scored
    OUTREACH_READY = "outreach_ready"  # draft generated, awaiting human review
    REJECTED       = "rejected"        # discarded by ICP (low score)


class FilterReason(str, Enum):
    """Reason a lead was discarded by the Filter Layer before ICP evaluation."""
    NO_WEBSITE            = "NO_WEBSITE"
    DUPLICATE             = "DUPLICATE"
    ENRICHMENT_FAILED     = "ENRICHMENT_FAILED"
    EXCLUDED_CATEGORY     = "EXCLUDED_CATEGORY"
    OUTSIDE_TARGET_REGION = "OUTSIDE_TARGET_REGION"
    COMPETITOR_SELLER     = "COMPETITOR_SELLER"   # Phase 1.5 Chunk 2


class BusinessType(str, Enum):
    """Detected business model of the target company."""
    B2B     = "B2B"
    B2C     = "B2C"
    UNKNOWN = "UNKNOWN"


class ICPDecision(str, Enum):
    """Final ICP evaluation decision."""
    QUALIFIED = "QUALIFIED"
    REJECTED  = "REJECTED"


class OutreachLanguage(str, Enum):
    """Language of the generated outreach message."""
    EN   = "EN"
    AR   = "AR"
    AUTO = "AUTO"  # resolved per-lead from enriched.language_of_website; falls back to AR


class LeadSource(str, Enum):
    """Where the lead was originally discovered."""
    GOOGLE_MAPS = "google_maps"


# ──────────────────────────────────────────────────────────────────────────────
# Stage 0 — Input (not frozen — caller-supplied, may be constructed incrementally)
# ──────────────────────────────────────────────────────────────────────────────

class BusinessContext(BaseModel):
    """
    Caller-supplied context that drives the entire pipeline.
    All fields are runtime-supplied — nothing is hardcoded.
    Only `industries` and `location` are required.
    Passed through every stage — never mutated by the pipeline.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    # ── Required ──────────────────────────────────────────────────────────────
    industries: list[NonEmptyStr] = Field(
        ...,
        min_length=1,
        description="Target industries (e.g. ['manufacturing', 'logistics'])",
        examples=[["manufacturing", "logistics"]],
    )
    location: NonEmptyStr = Field(
        ...,
        description="City or region to search in (e.g. 'Riyadh', 'Dubai', 'Cairo')",
    )

    # ── Optional search refinement ────────────────────────────────────────────
    country: Optional[str] = Field(
        default=None,
        description="Country name appended to search queries (e.g. 'Saudi Arabia', 'UAE', 'Egypt'). "
                    "If omitted, only location is used — no country appended.",
    )
    domain: Optional[str] = Field(
        default=None,
        description=(
            "Sub-sector of the TARGET companies (e.g. 'automobile parts', 'cold chain logistics', 'FMCG retail'). "
            "Describes what THEY do in more detail. "
            "Do NOT put your own services here — use our_services for that."
        ),
    )
    area: Optional[str] = Field(
        default=None,
        description="Sub-area or district within the city (e.g. 'King Abdullah Financial District')",
    )
    excluded_categories: list[str] = Field(
        default_factory=list,
        description="Google Maps categories to hard-discard (e.g. ['restaurant', 'clinic'])",
    )
    company_size_hint: Optional[str] = Field(
        default=None,
        description="e.g. 'SME', 'enterprise', '50-500 employees'",
    )

    # ── Outreach context (optional — used by ICP + outreach modules) ──────────
    pain_points: list[str] = Field(
        default_factory=list,
        description="Business transformation pain points we solve",
    )
    value_proposition: Optional[str] = Field(
        default=None,
        description="One-line value prop used in outreach drafts",
    )

    # ── Intent-aware targeting (Phase 1.5) ────────────────────────────────────
    our_services: list[str] = Field(
        default_factory=list,
        description=(
            "What WE provide — used to generate high-intent discovery queries. "
            "Separate from `domain` (what THEY do) and `value_proposition` (why they should care). "
            "Examples: ['ERP consulting', 'process automation', 'AI workflow implementation']"
        ),
    )
    target_pain_patterns: list[str] = Field(
        default_factory=list,
        description=(
            "Observable signals of companies likely to need our services. "
            "Used to sharpen discovery queries toward likely buyers. "
            "Examples: ['manual workflow bottlenecks', 'poor planning visibility', "
            "'inventory coordination issues']"
        ),
    )

    language_preference: OutreachLanguage = Field(
        default=OutreachLanguage.EN,
        description="Preferred outreach language. EN/AR for explicit, AUTO defaults to EN.",
    )
    notes: Optional[str] = Field(
        default=None,
        description="Free-text notes passed to ICP evaluator and outreach generator",
    )

    # ── Continuous run config (optional) ──────────────────────────────────────
    continuous: bool = Field(
        default=False,
        description="If True, pipeline repeats automatically after each run completes. "
                    "Stops when explicitly cancelled via DELETE /api/v1/leads/continuous/{config_id}.",
    )
    continuous_interval_minutes: int = Field(
        default=60,
        ge=15,
        description="Minutes to wait between continuous pipeline runs. Minimum 15.",
    )

    @field_validator("industries", "pain_points", "our_services", "target_pain_patterns", mode="before")
    @classmethod
    def _strip_list_strings(cls, v: list) -> list:
        return [s.strip() for s in v if isinstance(s, str) and s.strip()]


# ──────────────────────────────────────────────────────────────────────────────
# Base — shared traceability fields (all stage schemas inherit this)
# ──────────────────────────────────────────────────────────────────────────────

class _TraceableBase(BaseModel):
    """
    Internal base. Provides lead_id + trace_id on every stage schema.
    Not exported directly — use the concrete stage schemas.
    """

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    lead_id:  UUID4 = Field(default_factory=_new_uuid)
    trace_id: UUID4 = Field(default_factory=_new_uuid)


# ──────────────────────────────────────────────────────────────────────────────
# Stage 1 — RawLead  (Discovery output)
# ──────────────────────────────────────────────────────────────────────────────

class RawLead(_TraceableBase):
    """
    Produced by Discovery. Represents a single company found on Google Maps.

    lead_id   — stable identity across all pipeline stages (set here, never changes)
    trace_id  — equals lead_id in Phase 1; reserved for distributed tracing in Phase 2
    pipeline_run_id — links this lead to the /generate-leads call that created it
    """

    pipeline_run_id: UUID4 = Field(
        ...,
        description="ID of the pipeline run that produced this lead",
    )
    source: LeadSource = LeadSource.GOOGLE_MAPS
    discovered_at: datetime = Field(default_factory=_utcnow)
    status: LeadStatus = LeadStatus.RAW

    company_name: NonEmptyStr
    location: NonEmptyStr
    category: Optional[str] = None
    website: Optional[AnyHttpUrl] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    google_maps_url: Optional[AnyHttpUrl] = None
    rating: Optional[Annotated[float, Field(ge=0.0, le=5.0)]] = None
    review_count: Optional[Annotated[int, Field(ge=0)]] = None

    @field_validator("company_name", "location", mode="before")
    @classmethod
    def _no_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Field must not be blank")
        return v.strip()


# ──────────────────────────────────────────────────────────────────────────────
# Stage 2 — EnrichedLead  (Enrichment output)
# ──────────────────────────────────────────────────────────────────────────────

class EnrichedLead(_TraceableBase):
    """
    Produced by Enrichment. Carries all RawLead fields plus website-derived signals.
    enrichment_success=False does NOT stop the pipeline — Filter Layer decides fate.

    Immutable: created fresh from RawLead data, never mutates the RawLead.
    """

    # ── Traceability (forwarded from RawLead) ─────────────────────────────────
    pipeline_run_id: UUID4
    source: LeadSource
    discovered_at: datetime
    status: LeadStatus = LeadStatus.ENRICHED
    enriched_at: datetime = Field(default_factory=_utcnow)

    # ── Raw fields (forwarded unchanged) ──────────────────────────────────────
    company_name: NonEmptyStr
    location: NonEmptyStr
    category: Optional[str] = None
    website: Optional[AnyHttpUrl] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    rating: Optional[Annotated[float, Field(ge=0.0, le=5.0)]] = None
    review_count: Optional[Annotated[int, Field(ge=0)]] = None

    # ── Enrichment-derived fields ──────────────────────────────────────────────
    enrichment_success: bool
    summary: Optional[str] = None               # LLM-generated 2-3 sentence summary
    industry: Optional[str] = None              # detected primary industry
    business_type: BusinessType = BusinessType.UNKNOWN
    services_detected: list[str] = Field(default_factory=list)
    key_people: list[str] = Field(default_factory=list)
    contact_email: Optional[EmailStr] = None
    linkedin_url: Optional[AnyHttpUrl] = None   # found on website only — not scraped
    founding_year: Optional[Annotated[int, Field(ge=1900, le=2100)]] = None
    employee_count_hint: Optional[str] = None
    language_of_website: Optional[str] = None   # 'ar', 'en', or 'both'
    enrichment_error: Optional[str] = None      # set on partial/full failure

    @model_validator(mode="after")
    def _summary_required_on_success(self) -> "EnrichedLead":
        if self.enrichment_success and not self.summary:
            raise ValueError("summary must be provided when enrichment_success=True")
        return self


# ──────────────────────────────────────────────────────────────────────────────
# Stage 3 — FilteredLead  (Filter Layer output — terminal discard)
# ──────────────────────────────────────────────────────────────────────────────

class FilteredLead(_TraceableBase):
    """
    Produced by the Filter Layer for leads that fail structural checks.
    Terminal state — filtered leads are stored but never evaluated.

    Carries only the fields needed for audit and debugging.
    Does NOT inherit EnrichedLead to keep the discard record minimal.
    """

    pipeline_run_id: UUID4
    status: LeadStatus = LeadStatus.FILTERED
    filtered_at: datetime = Field(default_factory=_utcnow)

    # Audit fields
    company_name: NonEmptyStr
    location: NonEmptyStr
    category: Optional[str] = None
    website: Optional[AnyHttpUrl] = None
    enrichment_success: bool

    filter_reason: FilterReason


# ──────────────────────────────────────────────────────────────────────────────
# Stage 4 — EvaluatedLead  (ICP Evaluation output)
# ──────────────────────────────────────────────────────────────────────────────

class ICPRuleResult(BaseModel):
    """Result of a single ICP rule check. Immutable."""

    model_config = ConfigDict(frozen=True)

    rule_name: NonEmptyStr
    passed: bool
    reason: NonEmptyStr
    weight: Annotated[float, Field(ge=0.0, le=1.0)] = 1.0


class EvaluatedLead(_TraceableBase):
    """
    Produced by ICP Evaluation.

    fit_score    — composite score (0–100), computed by caller from rule + llm scores
    rule_score   — deterministic rule engine score (0–100), always present
    llm_score    — LLM-derived score (0–100), only present when llm_was_called=True
    llm_was_called — audit flag: was LLM invoked for this lead?
    confidence_score — overall confidence (0–1)
    decision     — QUALIFIED or REJECTED

    LLM is only called when rule_score >= 45. Schema enforces this via validator.
    """

    pipeline_run_id: UUID4
    status: LeadStatus = LeadStatus.EVALUATED
    evaluated_at: datetime = Field(default_factory=_utcnow)

    # Forwarded identity fields
    company_name: NonEmptyStr
    location: NonEmptyStr
    website: Optional[AnyHttpUrl] = None

    # Scores
    fit_score:        Score100
    rule_score:       Score100
    llm_score:        Optional[Score100] = None
    llm_was_called:   bool = False
    confidence_score: UnitFloat

    # Decision
    decision: ICPDecision
    rule_results: list[ICPRuleResult] = Field(default_factory=list)
    llm_reasoning: Optional[str] = None
    disqualification_reason: Optional[str] = None

    @model_validator(mode="after")
    def _llm_consistency(self) -> "EvaluatedLead":
        if self.llm_was_called and self.llm_score is None:
            raise ValueError("llm_score must be provided when llm_was_called=True")
        if not self.llm_was_called and self.llm_score is not None:
            raise ValueError("llm_score must be None when llm_was_called=False")
        return self

    @model_validator(mode="after")
    def _rejection_requires_reason(self) -> "EvaluatedLead":
        if self.decision == ICPDecision.REJECTED and not self.disqualification_reason:
            raise ValueError("disqualification_reason required when decision=REJECTED")
        return self


# ──────────────────────────────────────────────────────────────────────────────
# Stage 5 — OutreachOutput  (Outreach Generation output)
# ──────────────────────────────────────────────────────────────────────────────

class OutreachOutput(_TraceableBase):
    """
    Produced by Outreach Generation.

    approved is ALWAYS False at creation — this system never sends messages.
    A human must review and set approved=True externally before any send.

    word_count is computed automatically from email_body.
    Validation rejects messages that exceed max_allowed_words.
    """

    pipeline_run_id: UUID4
    generated_at: datetime = Field(default_factory=_utcnow)

    email_subject: Annotated[str, Field(min_length=1, max_length=80)]
    email_body:    Annotated[str, Field(min_length=1, max_length=2000)]
    language:      OutreachLanguage
    max_allowed_words: Annotated[int, Field(ge=1)] = 300

    personalization_hooks: list[str] = Field(default_factory=list)

    # Human review gate — mandatory, hardcoded False
    approved: bool = False
    reviewer_notes: Optional[str] = None

    @computed_field  # type: ignore[misc]
    @property
    def word_count(self) -> int:
        """Automatically computed from email_body. Cannot be set manually."""
        return len(self.email_body.split())

    @model_validator(mode="after")
    def _enforce_word_limit(self) -> "OutreachOutput":
        if self.word_count > self.max_allowed_words:
            raise ValueError(
                f"email_body has {self.word_count} words, "
                f"exceeds max_allowed_words={self.max_allowed_words}"
            )
        return self

    @model_validator(mode="after")
    def _approved_must_be_false(self) -> "OutreachOutput":
        if self.approved is not False:
            raise ValueError(
                "approved must be False at creation — "
                "set it externally after human review"
            )
        return self
