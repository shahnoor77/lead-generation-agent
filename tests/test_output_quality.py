"""
Output Quality Validator tests (Phase 1.5 Chunk 3).
Pure unit tests — no LLM, no network.
"""

import pytest
from app.modules.quality.output_quality_validator import (
    validate_summary, summary_fallback,
    validate_outreach, outreach_fallback,
    validate_icp_reasoning, icp_reasoning_fallback,
)


# ── Summary validation ────────────────────────────────────────────────────────

def test_good_summary_passes():
    summary = "Riyadh Steel operates three manufacturing facilities producing structural steel components for construction projects across Saudi Arabia. The company manages its own logistics fleet and serves major contractors in the region."
    r = validate_summary(summary, "Riyadh Steel")
    assert r.passed


def test_empty_summary_fails():
    r = validate_summary("", "Test Co")
    assert not r.passed
    assert any("empty" in i for i in r.issues)


def test_too_short_summary_fails():
    r = validate_summary("A company.", "Test Co")
    assert not r.passed
    assert any("short" in i for i in r.issues)


def test_generic_phrase_fails():
    r = validate_summary("Test Co is a leading provider of innovative solutions committed to excellence.", "Test Co")
    assert not r.passed
    assert any("generic" in i for i in r.issues)


def test_multiple_generic_phrases_fail():
    r = validate_summary("A trusted partner offering world-class cutting-edge solutions.", "Test Co")
    assert not r.passed


def test_summary_fallback_is_safe():
    fb = summary_fallback("ACME Corp", "Manufacturing", "Riyadh")
    assert "ACME Corp" in fb
    assert len(fb.split()) >= 5
    assert "[auto-fallback]" not in fb  # tag added by summarizer, not fallback fn


# ── Outreach validation ───────────────────────────────────────────────────────

def test_good_outreach_passes():
    subject = "Operational efficiency for Gulf Freight"
    body = (
        "Logistics companies managing multi-warehouse operations often encounter coordination gaps "
        "that create hidden costs in last-mile delivery. Gulf Freight's scale across the region "
        "suggests this may be a familiar challenge. We've helped similar operators reduce these "
        "inefficiencies by 20-30% through targeted process improvements. Would a 15-minute call "
        "be worth exploring whether there's a relevant fit for your operations?"
    )
    r = validate_outreach(subject, body, "Gulf Freight")
    assert r.passed


def test_spam_opener_fails():
    subject = "Quick question"
    body = "I hope this email finds you well. I wanted to reach out about our services."
    r = validate_outreach(subject, body, "Test Co")
    assert not r.passed
    assert any("opener" in i for i in r.issues)


def test_assumption_as_fact_fails():
    subject = "Improving your operations"
    body = "Your company is struggling with operational inefficiency and your team is dealing with poor planning. We can fix this."
    r = validate_outreach(subject, body, "Test Co")
    assert not r.passed
    assert any("assumption" in i for i in r.issues)


def test_generic_filler_in_body_fails():
    subject = "Partnership opportunity"
    body = "We are a leading provider of innovative solutions and trusted partner for world-class enterprises. Let us help you leverage synergy."
    r = validate_outreach(subject, body, "Test Co")
    assert not r.passed


def test_empty_body_fails():
    r = validate_outreach("Subject here", "", "Test Co")
    assert not r.passed
    assert any("empty" in i for i in r.issues)


def test_outreach_fallback_is_safe():
    subject, body = outreach_fallback("ACME Corp")
    assert "ACME Corp" in subject or "ACME Corp" in body
    assert len(body.split()) >= 20
    # Fallback must not contain spam openers
    assert "i hope this email" not in body.lower()
    assert "i wanted to reach out" not in body.lower()


# ── ICP reasoning validation ──────────────────────────────────────────────────

def test_good_reasoning_passes():
    r = validate_icp_reasoning(
        "Mid-sized manufacturer with multi-site operations showing clear supply planning complexity — strong buyer profile for ERP optimization.",
        "ACME Manufacturing"
    )
    assert r.passed


def test_empty_reasoning_fails():
    r = validate_icp_reasoning("", "Test Co")
    assert not r.passed


def test_too_short_reasoning_fails():
    r = validate_icp_reasoning("Good fit.", "Test Co")
    assert not r.passed


def test_generic_reasoning_fails():
    r = validate_icp_reasoning("This company is a leading provider of innovative solutions.", "Test Co")
    assert not r.passed


def test_reasoning_without_specifics_fails():
    r = validate_icp_reasoning("The company scored well on all criteria and appears to be a good match.", "Test Co")
    assert not r.passed
    assert any("specific" in i for i in r.issues)


def test_icp_reasoning_fallback_is_safe():
    fb = icp_reasoning_fallback("Test Co", 65)
    assert "Test Co" in fb
    assert "65" in fb
