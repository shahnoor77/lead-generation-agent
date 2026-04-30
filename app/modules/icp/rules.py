"""
Rule-based ICP filter — deterministic, fast, no LLM needed.
Rules are intentionally simple and easy to extend.
Each rule returns an ICPRuleResult — no side effects, no mutations.
"""

from app.schemas import EnrichedLead, BusinessContext, ICPRuleResult


class RuleEngine:
    def run(self, lead: EnrichedLead, context: BusinessContext) -> list[ICPRuleResult]:
        return [
            self._rule_has_website(lead),
            self._rule_industry_match(lead, context),
            self._rule_has_contact(lead),
            self._rule_not_micro_business(lead),
            self._rule_ksa_presence(lead, context),
        ]

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
