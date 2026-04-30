"""
Output Quality Validator — Phase 1.5 Chunk 3

Validates LLM outputs before they are stored or used downstream.
Deterministic checks run first. No LLM needed for validation.

Validates:
  - Enrichment summaries (plain text)
  - Outreach drafts (JSON with subject_line + message_body)
  - ICP reasoning (string)

Returns ValidationResult with:
  - passed: bool
  - issues: list of specific failure reasons
  - source: "llm" | "fallback"

Fallback values are safe, minimal, and clearly marked.
Never stores bad content. Never fails silently.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from app.core.logging import get_logger

logger = get_logger(__name__)

# ── Generic filler phrases that indicate low-quality LLM output ───────────────
_GENERIC_PHRASES = {
    "leading provider",
    "innovative solutions",
    "trusted partner",
    "world-class",
    "cutting-edge",
    "comprehensive services",
    "offers a wide range",
    "dedicated to",
    "committed to",
    "strives to",
    "state-of-the-art",
    "best-in-class",
    "synergy",
    "leverage",
    "paradigm",
    "holistic approach",
    "end-to-end solutions",
    "value-added",
    "one-stop shop",
}

# ── Spam/generic outreach openers ─────────────────────────────────────────────
_SPAM_OPENERS = {
    "i hope this email finds you",
    "i hope you are doing well",
    "i hope this message finds you",
    "my name is",
    "i wanted to reach out",
    "i am writing to",
    "we are a leading",
    "we are pleased to",
    "allow me to introduce",
    "hope this finds you",
    "i trust this email",
    "as a leading",
}

# ── Minimum useful lengths ─────────────────────────────────────────────────────
_MIN_SUMMARY_WORDS = 15
_MIN_SUBJECT_WORDS = 3
_MIN_BODY_WORDS = 30
_MAX_BODY_WORDS = 300


@dataclass
class ValidationResult:
    passed: bool
    issues: list[str] = field(default_factory=list)
    source: str = "llm"          # "llm" | "fallback"

    def add_issue(self, msg: str) -> None:
        self.issues.append(msg)
        self.passed = False


# ── Summary validator ─────────────────────────────────────────────────────────

def validate_summary(text: str, company_name: str) -> ValidationResult:
    """
    Validates an enrichment summary.
    Returns ValidationResult — caller decides whether to use fallback.
    """
    result = ValidationResult(passed=True)
    text_lower = text.lower().strip()

    # 1. Empty or whitespace
    if not text_lower:
        result.add_issue("summary is empty")
        return result

    # 2. Too short to be useful
    word_count = len(text.split())
    if word_count < _MIN_SUMMARY_WORDS:
        result.add_issue(f"summary too short ({word_count} words, min {_MIN_SUMMARY_WORDS})")

    # 3. Generic filler phrases
    found_generic = [p for p in _GENERIC_PHRASES if p in text_lower]
    if found_generic:
        result.add_issue(f"generic filler phrases detected: {found_generic[:3]}")

    # 4. Repeated content (summary is just the company name repeated)
    if text_lower.count(company_name.lower()) > 3:
        result.add_issue("summary repeats company name excessively")

    # 5. Hallucination signal: summary is longer than 5 sentences
    sentences = [s.strip() for s in text.split(".") if s.strip()]
    if len(sentences) > 5:
        result.add_issue(f"summary too long ({len(sentences)} sentences, max 5)")

    if not result.passed:
        logger.warning(
            "quality.summary_failed",
            company=company_name,
            issues=result.issues,
            preview=text[:100],
        )

    return result


def summary_fallback(company_name: str, category: str | None = None, location: str | None = None) -> str:
    """Safe fallback summary when LLM output fails validation."""
    parts = [f"{company_name} operates"]
    if category:
        parts.append(f"in the {category} sector")
    if location:
        parts.append(f"in {location}")
    parts.append("with insufficient public detail available for strong qualification.")
    return " ".join(parts)


# ── Outreach draft validator ──────────────────────────────────────────────────

def validate_outreach(subject: str, body: str, company_name: str) -> ValidationResult:
    """
    Validates an outreach draft (subject + body).
    """
    result = ValidationResult(passed=True)
    subject_lower = subject.lower().strip()
    body_lower = body.lower().strip()

    # 1. Empty fields
    if not subject_lower:
        result.add_issue("subject line is empty")
    if not body_lower:
        result.add_issue("message body is empty")
        return result

    # 2. Subject too short
    if len(subject.split()) < _MIN_SUBJECT_WORDS:
        result.add_issue(f"subject too short ({len(subject.split())} words)")

    # 3. Body too short
    body_words = len(body.split())
    if body_words < _MIN_BODY_WORDS:
        result.add_issue(f"body too short ({body_words} words, min {_MIN_BODY_WORDS})")

    # 4. Body too long
    if body_words > _MAX_BODY_WORDS:
        result.add_issue(f"body too long ({body_words} words, max {_MAX_BODY_WORDS})")

    # 5. Spam/generic openers
    first_sentence = body_lower[:120]
    found_spam = [p for p in _SPAM_OPENERS if p in first_sentence]
    if found_spam:
        result.add_issue(f"spam/generic opener detected: {found_spam[0]!r}")

    # 6. Generic filler phrases in body
    found_generic = [p for p in _GENERIC_PHRASES if p in body_lower]
    if found_generic:
        result.add_issue(f"generic filler in body: {found_generic[:2]}")

    # 7. Assumption stated as fact (hard assertions about the company)
    assumption_phrases = [
        "your company is struggling",
        "you are facing",
        "your team is dealing with",
        "you currently have",
        "your business lacks",
    ]
    found_assumptions = [p for p in assumption_phrases if p in body_lower]
    if found_assumptions:
        result.add_issue(f"assumption stated as fact: {found_assumptions[0]!r}")

    # 8. Repeated content (body contains company name too many times)
    if body_lower.count(company_name.lower()) > 4:
        result.add_issue("company name repeated excessively in body")

    if not result.passed:
        logger.warning(
            "quality.outreach_failed",
            company=company_name,
            issues=result.issues,
            subject=subject[:80],
        )

    return result


def outreach_fallback(company_name: str) -> tuple[str, str]:
    """
    Safe fallback outreach draft when LLM output fails validation.
    Returns (subject, body) — minimal, professional, clearly a placeholder.
    """
    subject = f"Quick question for {company_name}"
    body = (
        f"I came across {company_name} and wanted to reach out briefly. "
        f"We work with companies in your sector on operational efficiency initiatives, "
        f"and I thought there might be a relevant conversation worth having. "
        f"Would you be open to a 15-minute call to explore if there's a fit? "
        f"No pressure — happy to share more context first if useful."
    )
    return subject, body


# ── ICP reasoning validator ───────────────────────────────────────────────────

def validate_icp_reasoning(reasoning: str, company_name: str) -> ValidationResult:
    """
    Validates ICP reasoning text.
    """
    result = ValidationResult(passed=True)
    text_lower = reasoning.lower().strip()

    if not text_lower:
        result.add_issue("reasoning is empty")
        return result

    if len(reasoning.split()) < 8:
        result.add_issue(f"reasoning too short ({len(reasoning.split())} words)")

    found_generic = [p for p in _GENERIC_PHRASES if p in text_lower]
    if found_generic:
        result.add_issue(f"generic phrases in reasoning: {found_generic[:2]}")

    # Reasoning should mention something specific — at least one of these signals
    specificity_signals = [
        "manufactur", "logistic", "warehouse", "hospital", "retail",
        "construction", "supply", "operation", "facility", "plant",
        "distribution", "production", "scale", "complex", "buyer",
        "erp", "digital", "transform", "process", "workflow",
    ]
    has_specific = any(s in text_lower for s in specificity_signals)
    if not has_specific:
        result.add_issue("reasoning lacks specific business signals")

    if not result.passed:
        logger.warning(
            "quality.icp_reasoning_failed",
            company=company_name,
            issues=result.issues,
        )

    return result


def icp_reasoning_fallback(company_name: str, rule_score: int) -> str:
    """Safe fallback ICP reasoning."""
    return (
        f"{company_name} scored {rule_score}/100 on rule-based evaluation. "
        f"Insufficient LLM reasoning available — operator review recommended."
    )
