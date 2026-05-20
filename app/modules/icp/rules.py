"""
Rule-based ICP filter — deterministic, fast, no LLM needed.
Rules are intentionally simple and easy to extend.
Each rule returns an ICPRuleResult — no side effects, no mutations.

Scoring is weighted per-dimension using user-configured ICPScoringWeights.
Dimensions: industry_match, revenue_fit, location, digital_presence, firmographic_quality
"""

from __future__ import annotations
from app.schemas import EnrichedLead, BusinessContext, ICPRuleResult
from app.schemas.settings import ICPScoringWeights


class RuleEngine:
    def run(
        self,
        lead: EnrichedLead,
        context: BusinessContext,
        icp_settings=None,  # ICPSettings | None
    ) -> list[ICPRuleResult]:
        return [
            self._rule_has_website(lead),
            self._rule_industry_match(lead, context),
            self._rule_has_contact(lead),
            self._rule_not_micro_business(lead),
            self._rule_ksa_presence(lead, context),
            self._rule_revenue_fit(lead, icp_settings),
            self._rule_decision_maker_title(lead, icp_settings),
            self._rule_ownership_type(lead, icp_settings),
        ]

    def weighted_score(
        self,
        lead: EnrichedLead,
        context: BusinessContext,
        rule_results: list[ICPRuleResult],
        weights: ICPScoringWeights | None = None,
    ) -> int:
        """
        Compute a weighted ICP score (0–100) from rule results.
        Each dimension maps to one or more rules. Weights are normalised.
        """
        if weights is None:
            weights = ICPScoringWeights()

        # Map rule names → dimension
        dimension_rules: dict[str, list[str]] = {
            "industry_match":       ["industry_match"],
            "revenue_fit":          ["revenue_fit"],
            "location":             ["location_presence"],
            "digital_presence":     ["has_website"],
            "firmographic_quality": ["has_contact", "not_micro_business", "decision_maker_title", "ownership_type"],
        }

        rule_map = {r.rule_name: r.passed for r in rule_results}

        total_weight = 0
        weighted_sum = 0.0

        for dim, rule_names in dimension_rules.items():
            w = getattr(weights, dim, 0)
            if w <= 0:
                continue
            # Dimension passes if ANY of its rules pass
            passed = any(rule_map.get(rn, False) for rn in rule_names)
            weighted_sum += w * (1.0 if passed else 0.0)
            total_weight += w

        if total_weight == 0:
            # Fallback: simple pass ratio
            passed_count = sum(1 for r in rule_results if r.passed)
            return round((passed_count / len(rule_results)) * 100) if rule_results else 0

        return round((weighted_sum / total_weight) * 100)

    def _rule_has_website(self, lead: EnrichedLead) -> ICPRuleResult:
        passed = lead.website is not None
        return ICPRuleResult(
            rule_name="has_website",
            passed=passed,
            reason="Company has a website" if passed else "No website found — hard to research",
        )

    def _rule_industry_match(self, lead: EnrichedLead, context: BusinessContext) -> ICPRuleResult:
        # Build search corpus from lead signals
        text = " ".join([
            lead.company_name,
            lead.category or "",
            lead.summary or "",
            lead.industry or "",
            " ".join(lead.services_detected),
        ]).lower()

        # Match against industries, domain, AND our_services for richer signal
        keywords = list(context.industries)
        if context.domain:
            keywords.append(context.domain)
        if context.our_services:
            keywords.extend(context.our_services)

        matched = [kw for kw in keywords if kw.lower() in text]
        passed = len(matched) > 0
        return ICPRuleResult(
            rule_name="industry_match",
            passed=passed,
            reason=f"Matched keywords: {matched}" if passed else "No industry/domain/service keyword match",
        )

    def _rule_has_contact(self, lead: EnrichedLead) -> ICPRuleResult:
        passed = bool(lead.contact_email or lead.phone)
        return ICPRuleResult(
            rule_name="has_contact",
            passed=passed,
            reason="Has reachable contact" if passed else "No email or phone found",
        )

    def _rule_not_micro_business(self, lead: EnrichedLead) -> ICPRuleResult:
        is_micro = (
            lead.review_count is not None
            and lead.review_count < 5
            and not lead.website
        )
        passed = not is_micro
        return ICPRuleResult(
            rule_name="not_micro_business",
            passed=passed,
            reason="Appears to be a real business" if passed else "Likely micro/sole trader",
        )

    def _rule_ksa_presence(self, lead: EnrichedLead, context: BusinessContext) -> ICPRuleResult:
        # Build signals from whatever the user specified — not hardcoded to KSA
        signals: list[str] = []
        for part in context.location.lower().split():
            if len(part) > 2:
                signals.append(part)
        if context.country:
            for part in context.country.lower().split():
                if len(part) > 2:
                    signals.append(part)
        # Fallback signals if nothing useful derived
        if not signals:
            signals = ["saudi", "ksa", "riyadh", "jeddah", "dammam", "المملكة", "الرياض"]

        text = " ".join([lead.location, lead.address or "", lead.summary or ""]).lower()
        passed = any(s in text for s in signals)
        target = f"{context.location}{', ' + context.country if context.country else ''}"
        return ICPRuleResult(
            rule_name="location_presence",
            passed=passed,
            reason=f"Confirmed presence in {target}" if passed else f"Location signal for '{target}' not found",
        )

    def _rule_revenue_fit(self, lead: EnrichedLead, icp_settings=None) -> ICPRuleResult:
        """Pass if no revenue constraints set, or if lead revenue signals fit the range."""
        if icp_settings is None or (icp_settings.revenue_min is None and icp_settings.revenue_max is None):
            return ICPRuleResult(
                rule_name="revenue_fit",
                passed=True,
                reason="No revenue constraints configured",
            )
        # We don't have structured revenue data from scraping — use review count as a proxy
        # A company with 50+ reviews is likely not micro; treat as passing revenue check
        review_count = lead.review_count or 0
        passed = review_count >= 10  # rough proxy for established business
        return ICPRuleResult(
            rule_name="revenue_fit",
            passed=passed,
            reason="Revenue proxy (review count) suggests established business" if passed
                   else "Too few signals to confirm revenue fit",
        )

    def _rule_decision_maker_title(self, lead: EnrichedLead, icp_settings=None) -> ICPRuleResult:
        """Check if any key person on the lead matches configured decision maker titles."""
        if icp_settings is None or not icp_settings.decision_maker_titles:
            return ICPRuleResult(
                rule_name="decision_maker_title",
                passed=True,
                reason="No decision maker title filter configured",
            )
        titles_lower = [t.lower() for t in icp_settings.decision_maker_titles]
        text = " ".join(lead.key_people).lower() if lead.key_people else ""
        if not text:
            # No key people data — don't penalise, just pass
            return ICPRuleResult(
                rule_name="decision_maker_title",
                passed=True,
                reason="No key people data available — skipping title check",
            )
        matched = [t for t in titles_lower if t in text]
        passed = len(matched) > 0
        return ICPRuleResult(
            rule_name="decision_maker_title",
            passed=passed,
            reason=f"Decision maker title matched: {matched}" if passed
                   else "No configured decision maker title found in key people",
        )

    def _rule_ownership_type(self, lead: EnrichedLead, icp_settings=None) -> ICPRuleResult:
        """Check if lead's business type matches configured ownership types."""
        if icp_settings is None or not icp_settings.ownership_types:
            return ICPRuleResult(
                rule_name="ownership_type",
                passed=True,
                reason="No ownership type filter configured",
            )
        types_lower = [t.lower() for t in icp_settings.ownership_types]
        text = " ".join([
            lead.business_type or "",
            lead.summary or "",
            lead.category or "",
        ]).lower()
        matched = [t for t in types_lower if t in text]
        # If no signal at all, pass (don't penalise missing data)
        passed = len(matched) > 0 or not text.strip()
        return ICPRuleResult(
            rule_name="ownership_type",
            passed=passed,
            reason=f"Ownership type matched: {matched}" if matched
                   else "No ownership type signal found — not penalised",
        )
