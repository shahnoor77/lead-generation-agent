"""
Opportunity Query Builder — unit tests (Phase 1.5 Chunk 1).
No LLM, no network. Tests rule-based query generation only.
"""

import pytest
from app.schemas import BusinessContext, OutreachLanguage
from app.modules.discovery.query_builder import build_rule_based_queries, _build_baseline, _location_suffix


def _ctx(**kwargs) -> BusinessContext:
    base = dict(industries=["manufacturing"], location="Riyadh")
    base.update(kwargs)
    return BusinessContext(**base)


# ── Location suffix ───────────────────────────────────────────────────────────

def test_location_suffix_city_only():
    ctx = _ctx(location="Riyadh")
    suffix = _location_suffix(ctx)
    assert "Riyadh" in suffix


def test_location_suffix_with_country():
    ctx = _ctx(location="Riyadh", country="Saudi Arabia")
    suffix = _location_suffix(ctx)
    assert "Riyadh" in suffix
    assert "Saudi Arabia" in suffix


def test_location_suffix_with_area():
    ctx = _ctx(location="Riyadh", area="KAFD", country="Saudi Arabia")
    suffix = _location_suffix(ctx)
    assert "KAFD" in suffix
    assert "Riyadh" in suffix


# ── Baseline query ────────────────────────────────────────────────────────────

def test_baseline_industry_only():
    ctx = _ctx(location="Dubai")
    q = _build_baseline("logistics", ctx, _location_suffix(ctx))
    assert "logistics" in q
    assert "Dubai" in q


def test_baseline_with_domain():
    """domain is no longer included in queries — it's for ICP/outreach context only."""
    ctx = _ctx(location="Riyadh", domain="ERP", country="Saudi Arabia")
    q = _build_baseline("manufacturing", ctx, _location_suffix(ctx))
    assert "manufacturing" in q
    assert "Riyadh" in q
    # domain intentionally excluded from queries to prevent result pollution
    assert "ERP" not in q


# ── Rule-based queries ────────────────────────────────────────────────────────

def test_no_services_returns_baseline_only():
    ctx = _ctx(location="Riyadh", country="Saudi Arabia")
    queries = build_rule_based_queries(ctx)
    assert len(queries) >= 1
    assert any("manufacturing" in q for q in queries)


def test_our_services_does_not_appear_in_queries():
    """our_services must NOT appear in discovery queries — that finds competitors, not buyers."""
    ctx = _ctx(
        location="Riyadh",
        country="Saudi Arabia",
        our_services=["ERP consulting", "process automation"],
    )
    queries = build_rule_based_queries(ctx)
    for q in queries:
        assert "ERP consulting" not in q, f"our_services leaked into query: {q}"
        assert "process automation" not in q, f"our_services leaked into query: {q}"


def test_pain_patterns_generate_pain_angle_queries():
    ctx = _ctx(
        location="Riyadh",
        target_pain_patterns=["manual workflow bottlenecks", "poor planning visibility"],
    )
    queries = build_rule_based_queries(ctx)
    assert any("manual workflow bottlenecks" in q for q in queries)


def test_all_queries_contain_location():
    ctx = _ctx(
        location="Dubai",
        country="UAE",
        our_services=["AI consulting"],
        target_pain_patterns=["operational inefficiency"],
    )
    queries = build_rule_based_queries(ctx)
    for q in queries:
        assert "Dubai" in q or "UAE" in q, f"Query missing location: {q}"


def test_no_duplicate_queries():
    ctx = _ctx(
        location="Riyadh",
        our_services=["ERP"],
        target_pain_patterns=["inefficiency"],
    )
    queries = build_rule_based_queries(ctx)
    assert len(queries) == len(set(queries))


def test_multiple_industries():
    ctx = _ctx(
        industries=["manufacturing", "logistics"],
        location="Riyadh",
        our_services=["ERP consulting"],
    )
    queries = build_rule_based_queries(ctx)
    has_manufacturing = any("manufacturing" in q for q in queries)
    has_logistics = any("logistics" in q for q in queries)
    assert has_manufacturing
    assert has_logistics


def test_empty_services_and_patterns_still_works():
    ctx = _ctx(location="Cairo", country="Egypt", our_services=[], target_pain_patterns=[])
    queries = build_rule_based_queries(ctx)
    assert len(queries) >= 1


# ── BusinessContext new fields ────────────────────────────────────────────────

def test_our_services_field_accepted():
    ctx = BusinessContext(
        industries=["retail"],
        location="Jeddah",
        our_services=["supply chain optimization", "inventory management"],
    )
    assert ctx.our_services == ["supply chain optimization", "inventory management"]


def test_target_pain_patterns_field_accepted():
    ctx = BusinessContext(
        industries=["healthcare"],
        location="Dammam",
        target_pain_patterns=["manual patient tracking", "compliance overhead"],
    )
    assert len(ctx.target_pain_patterns) == 2


def test_new_fields_stripped():
    ctx = BusinessContext(
        industries=["tech"],
        location="Riyadh",
        our_services=["  AI consulting  ", " process automation "],
        target_pain_patterns=["  bottlenecks  "],
    )
    assert ctx.our_services == ["AI consulting", "process automation"]
    assert ctx.target_pain_patterns == ["bottlenecks"]


def test_new_fields_default_empty():
    ctx = BusinessContext(industries=["manufacturing"], location="Riyadh")
    assert ctx.our_services == []
    assert ctx.target_pain_patterns == []
