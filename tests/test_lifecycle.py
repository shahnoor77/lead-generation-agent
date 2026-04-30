"""
Lead Lifecycle State Tracking — unit tests.
No DB, no network. Tests enum logic and transition rules only.
"""

import pytest
from app.schemas.lifecycle import (
    LeadLifecycleStatus,
    is_pipeline_status,
    is_valid_transition,
    ALLOWED_TRANSITIONS,
)


# ── Enum completeness ─────────────────────────────────────────────────────────

def test_all_statuses_defined():
    expected = {
        "DISCOVERED", "ENRICHED", "QUALIFIED", "OUTREACH_DRAFTED",
        "READY_FOR_REVIEW", "READY_TO_SEND", "CONTACTED",
        "REPLIED", "MEETING_SCHEDULED", "WON", "LOST", "ARCHIVED",
    }
    actual = {s.value for s in LeadLifecycleStatus}
    assert actual == expected


# ── Pipeline vs human statuses ────────────────────────────────────────────────

def test_pipeline_statuses_identified():
    assert is_pipeline_status(LeadLifecycleStatus.DISCOVERED)
    assert is_pipeline_status(LeadLifecycleStatus.ENRICHED)
    assert is_pipeline_status(LeadLifecycleStatus.QUALIFIED)
    assert is_pipeline_status(LeadLifecycleStatus.OUTREACH_DRAFTED)


def test_human_statuses_not_pipeline():
    assert not is_pipeline_status(LeadLifecycleStatus.READY_FOR_REVIEW)
    assert not is_pipeline_status(LeadLifecycleStatus.CONTACTED)
    assert not is_pipeline_status(LeadLifecycleStatus.WON)


# ── Valid transitions ─────────────────────────────────────────────────────────

def test_happy_path_transitions():
    path = [
        (LeadLifecycleStatus.DISCOVERED,        LeadLifecycleStatus.ENRICHED),
        (LeadLifecycleStatus.ENRICHED,          LeadLifecycleStatus.QUALIFIED),
        (LeadLifecycleStatus.QUALIFIED,         LeadLifecycleStatus.OUTREACH_DRAFTED),
        (LeadLifecycleStatus.OUTREACH_DRAFTED,  LeadLifecycleStatus.READY_FOR_REVIEW),
        (LeadLifecycleStatus.READY_FOR_REVIEW,  LeadLifecycleStatus.READY_TO_SEND),
        (LeadLifecycleStatus.READY_TO_SEND,     LeadLifecycleStatus.CONTACTED),
        (LeadLifecycleStatus.CONTACTED,         LeadLifecycleStatus.REPLIED),
        (LeadLifecycleStatus.REPLIED,           LeadLifecycleStatus.MEETING_SCHEDULED),
        (LeadLifecycleStatus.MEETING_SCHEDULED, LeadLifecycleStatus.WON),
    ]
    for current, nxt in path:
        assert is_valid_transition(current, nxt), f"Expected valid: {current} → {nxt}"


def test_archive_allowed_from_most_statuses():
    archivable = [
        LeadLifecycleStatus.DISCOVERED,
        LeadLifecycleStatus.ENRICHED,
        LeadLifecycleStatus.QUALIFIED,
        LeadLifecycleStatus.OUTREACH_DRAFTED,
        LeadLifecycleStatus.READY_FOR_REVIEW,
        LeadLifecycleStatus.READY_TO_SEND,
        LeadLifecycleStatus.CONTACTED,
        LeadLifecycleStatus.REPLIED,
        LeadLifecycleStatus.MEETING_SCHEDULED,
        LeadLifecycleStatus.WON,
        LeadLifecycleStatus.LOST,
    ]
    for status in archivable:
        assert is_valid_transition(status, LeadLifecycleStatus.ARCHIVED), \
            f"Expected ARCHIVED to be reachable from {status}"


# ── Invalid transitions ───────────────────────────────────────────────────────

def test_skip_forward_invalid():
    # Cannot jump from DISCOVERED straight to CONTACTED
    assert not is_valid_transition(LeadLifecycleStatus.DISCOVERED, LeadLifecycleStatus.CONTACTED)


def test_backward_transition_invalid():
    assert not is_valid_transition(LeadLifecycleStatus.CONTACTED, LeadLifecycleStatus.DISCOVERED)
    assert not is_valid_transition(LeadLifecycleStatus.WON, LeadLifecycleStatus.QUALIFIED)


def test_archived_is_terminal():
    for status in LeadLifecycleStatus:
        if status != LeadLifecycleStatus.ARCHIVED:
            assert not is_valid_transition(LeadLifecycleStatus.ARCHIVED, status), \
                f"ARCHIVED should not transition to {status}"


def test_all_statuses_have_transition_rules():
    for status in LeadLifecycleStatus:
        assert status in ALLOWED_TRANSITIONS, f"Missing transition rules for {status}"
