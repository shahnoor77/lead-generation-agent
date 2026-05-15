from typing import Optional
from models.lead import Lead, Industry, EmailTone
import re

class EmailGenerator:
    INDUSTRY_TEMPLATES = {
        Industry.TECHNOLOGY: {
            "opening": "We've noticed {company_name}'s innovative approach to {focus_area}.",
            "value_prop": "Our solution can help optimize your tech stack and accelerate deployment cycles.",
            "cta": "We'd like to explore how we can support your team's growth."
        },
        Industry.FINANCE: {
            "opening": "{company_name} is excelling in {focus_area}, and we think there's an opportunity to enhance operations.",
            "value_prop": "Our platform provides advanced analytics and compliance automation for financial services.",
            "cta": "Let's discuss how we can add value to your financial operations."
        },
        Industry.HEALTHCARE: {
            "opening": "We've been impressed by {company_name}'s commitment to {focus_area}.",
            "value_prop": "Our healthcare solutions improve patient outcomes and streamline administrative processes.",
            "cta": "We'd appreciate the opportunity to demonstrate our platform."
        },
        Industry.MANUFACTURING: {
            "opening": "{company_name} is doing great work in {focus_area}.",
            "value_prop": "Our supply chain and operational software increases efficiency and reduces downtime.",
            "cta": "We'd like to show how other manufacturers are improving their bottom line."
        },
        # ...existing industries...
    }

    FORMAL_GREETINGS = [
        "Dear {title} {name}",
        "Dear {name}",
        "Dear {company} Team",
        "To the {title} at {company}",
    ]

    FORMAL_CLOSINGS = [
        "Best regards",
        "Sincerely",
        "Kind regards",
        "Respectfully",
    ]

    def __init__(self):
        self.tone_modifiers = {
            EmailTone.FORMAL: {
                "language": "formal",
                "urgency": "low",
                "personalization": "high"
            },
            EmailTone.PROFESSIONAL: {
                "language": "professional",
                "urgency": "medium",
                "personalization": "medium"
            },
            EmailTone.FRIENDLY: {
                "language": "conversational",
                "urgency": "low",
                "personalization": "high"
            },
            EmailTone.URGENT: {
                "language": "direct",
                "urgency": "high",
                "personalization": "medium"
            }
        }

    def generate_email(
        self,
        lead: Lead,
        tone: EmailTone = EmailTone.FORMAL,
        sender_name: str = "Your Company",
        sender_title: str = "Business Development",
    ) -> dict:
        """Generate a complete, personalized email for the lead."""
        
        subject = self._generate_subject(lead, tone)
        greeting = self._generate_greeting(lead)
        body = self._generate_body(lead, tone)
        closing = self._generate_closing(tone)
        signature = self._generate_signature(sender_name, sender_title)
        
        return {
            "to": lead.contact_email,
            "subject": subject,
            "greeting": greeting,
            "body": body,
            "closing": closing,
            "signature": signature,
            "full_email": self._assemble_email(greeting, body, closing, signature),
            "tone": tone.value,
            "personalization_score": self._calculate_personalization(lead)
        }

    def _generate_greeting(self, lead: Lead) -> str:
        """Generate formal, personalized greeting."""
        if lead.contact_name and lead.contact_title:
            return f"Dear {lead.contact_title} {lead.contact_name},"
        elif lead.contact_name:
            return f"Dear {lead.contact_name},"
        else:
            company_short = lead.company_name.split()[0]
            return f"Dear {company_short} Team,"

    def _generate_subject(self, lead: Lead, tone: EmailTone) -> str:
        """Generate industry-specific, compelling subject line."""
        subjects = {
            Industry.TECHNOLOGY: [
                f"Optimizing {lead.company_name}'s development velocity",
                f"New efficiency gains for {lead.company_name}'s engineering team",
                f"Accelerating innovation at {lead.company_name}"
            ],
            Industry.FINANCE: [
                f"Enhanced compliance for {lead.company_name}",
                f"Streamlining operations at {lead.company_name}",
                f"Advanced analytics for {lead.company_name}'s team"
            ],
            Industry.HEALTHCARE: [
                f"Improving patient outcomes at {lead.company_name}",
                f"Operational excellence for {lead.company_name}",
                f"Modernizing {lead.company_name}'s healthcare delivery"
            ],
            # ...existing industries...
        }
        
        industry_subjects = subjects.get(lead.industry, [])
        return industry_subjects[0] if industry_subjects else f"Partnership opportunity with {lead.company_name}"

    def _generate_body(self, lead: Lead, tone: EmailTone) -> str:
        """Generate industry-specific, company-specific body."""
        template = self.INDUSTRY_TEMPLATES.get(lead.industry, {})
        modifier = self.tone_modifiers[tone]
        
        focus_area = self._extract_focus_area(lead)
        
        opening = template.get("opening", "").format(
            company_name=lead.company_name,
            focus_area=focus_area
        )
        
        value_prop = template.get("value_prop", "")
        
        company_specific = self._generate_company_specific_paragraph(lead)
        
        cta = template.get("cta", "")
        
        body = f"{opening}\n\n{value_prop}\n\n{company_specific}\n\n{cta}"
        return self._adjust_tone(body, modifier)

    def _generate_company_specific_paragraph(self, lead: Lead) -> str:
        """Generate company-specific paragraph based on available data."""
        paragraphs = []
        
        if lead.company_size:
            paragraphs.append(f"As a {lead.company_size} organization, {lead.company_name} likely faces unique scalability challenges.")
        
        if lead.location:
            paragraphs.append(f"Your presence in {lead.location} positions you well in a dynamic market.")
        
        if lead.industry:
            paragraphs.append(f"The {lead.industry.value} sector demands constant innovation, which {lead.company_name} clearly embraces.")
        
        return " ".join(paragraphs) if paragraphs else f"We believe {lead.company_name} would benefit from our tailored solutions."

    def _generate_closing(self, tone: EmailTone) -> str:
        """Generate appropriate closing based on tone."""
        closing_map = {
            EmailTone.FORMAL: self.FORMAL_CLOSINGS[0],
            EmailTone.PROFESSIONAL: self.FORMAL_CLOSINGS[1],
            EmailTone.FRIENDLY: self.FORMAL_CLOSINGS[2],
            EmailTone.URGENT: self.FORMAL_CLOSINGS[0],
        }
        return closing_map[tone]

    def _generate_signature(self, sender_name: str, sender_title: str) -> str:
        """Generate professional signature."""
        return f"{sender_name}\n{sender_title}\nYour Company"

    def _assemble_email(self, greeting: str, body: str, closing: str, signature: str) -> str:
        """Assemble complete email."""
        return f"{greeting}\n\n{body}\n\n{closing}\n\n{signature}"

    def _extract_focus_area(self, lead: Lead) -> str:
        """Extract focus area from company description or tags."""
        if lead.tags:
            return lead.tags[0]
        if lead.description:
            words = lead.description.split()[:5]
            return " ".join(words)
        return "growth"

    def _adjust_tone(self, text: str, modifier: dict) -> str:
        """Adjust text tone based on modifiers."""
        if modifier["language"] == "formal":
            text = re.sub(r"we're", "we are", text)
            text = re.sub(r"let's", "let us", text)
        return text

    def _calculate_personalization(self, lead: Lead) -> float:
        """Score personalization level 0-100."""
        score = 0
        if lead.contact_name:
            score += 25
        if lead.contact_title:
            score += 15
        if lead.company_size:
            score += 15
        if lead.location:
            score += 15
        if lead.tags:
            score += 15
        if lead.industry:
            score += 15
        return min(score, 100)
