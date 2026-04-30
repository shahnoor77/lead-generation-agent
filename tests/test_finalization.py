"""
Draft Finalization Layer — unit tests (Chunk 2).
No DB, no network. Tests schema validation and business rules only.
"""

import pytest
from pydantic import ValidationError
from app.schemas.finalization import (
    FinalizeDraftRequest,
    ReceiverDetails,
    SenderDetails,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _receiver(**kwargs) -> dict:
    base = {
        "receiver_name": "Ahmed Khan",
        "receiver_role": "Operations Director",
        "receiver_email": "ahmed@abc.com",
        "preferred_contact_method": "email",
    }
    base.update(kwargs)
    return base


def _sender(**kwargs) -> dict:
    base = {
        "sender_name": "Ali Hassan",
        "sender_role": "Business Consultant",
        "sender_company": "XYZ Consulting",
        "sender_email": "ali@xyz.com",
        "sender_phone": "+966500000000",
        "signature": "Best regards,\nAli Hassan",
    }
    base.update(kwargs)
    return base


def _valid_request(**kwargs) -> dict:
    base = {
        "final_subject": "Reducing operational bottlenecks at ABC Manufacturing",
        "final_body": "Dear Mr. Ahmed, we help companies like yours improve efficiency.",
        "receiver_details": _receiver(),
        "sender_details": _sender(),
        "finalized_by": "ali.hassan",
    }
    base.update(kwargs)
    return base


# ── Schema validation ─────────────────────────────────────────────────────────

def test_valid_request_parses():
    req = FinalizeDraftRequest(**_valid_request())
    assert req.final_subject == "Reducing operational bottlenecks at ABC Manufacturing"
    assert req.receiver_details.receiver_name == "Ahmed Khan"
    assert req.sender_details.sender_name == "Ali Hassan"


def test_receiver_email_validated():
    with pytest.raises(ValidationError):
        ReceiverDetails(**_receiver(receiver_email="not-an-email"))


def test_sender_email_validated():
    with pytest.raises(ValidationError):
        SenderDetails(**_sender(sender_email="bad"))


def test_receiver_name_required():
    with pytest.raises(ValidationError):
        ReceiverDetails(**_receiver(receiver_name=""))


def test_sender_name_required():
    with pytest.raises(ValidationError):
        SenderDetails(**_sender(sender_name=""))


def test_final_subject_required():
    with pytest.raises(ValidationError):
        FinalizeDraftRequest(**_valid_request(final_subject=""))


def test_final_body_required():
    with pytest.raises(ValidationError):
        FinalizeDraftRequest(**_valid_request(final_body=""))


# ── Optional fields ───────────────────────────────────────────────────────────

def test_optional_fields_default_to_none():
    req = FinalizeDraftRequest(**_valid_request(finalized_by=None, notes=None))
    assert req.finalized_by is None
    assert req.notes is None


def test_receiver_linkedin_optional():
    r = ReceiverDetails(**_receiver())
    assert r.linkedin_url is None


def test_sender_phone_optional():
    data = _sender()
    del data["sender_phone"]
    s = SenderDetails(**data)
    assert s.sender_phone is None


# ── Approval rules ────────────────────────────────────────────────────────────

def test_approval_status_not_in_request():
    """Approval status must not be settable via the finalize request."""
    req_data = _valid_request()
    req_data["approval_status"] = "APPROVED"   # should be ignored (extra field)
    # Pydantic ignores extra fields by default — no crash, no approval
    req = FinalizeDraftRequest(**req_data)
    assert not hasattr(req, "approval_status")


def test_finalize_request_has_no_approved_field():
    """The request schema must not expose an approved/approval_status field."""
    fields = set(FinalizeDraftRequest.model_fields.keys())
    assert "approved" not in fields
    assert "approval_status" not in fields
    assert "approved_by" not in fields
