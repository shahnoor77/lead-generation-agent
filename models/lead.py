from dataclasses import dataclass, field
from typing import Optional, Dict, List
from enum import Enum
from datetime import datetime

class EmailTone(Enum):
    PROFESSIONAL = "professional"
    CASUAL = "casual"
    URGENT = "urgent"
    FRIENDLY = "friendly"
    FORMAL = "formal"

class ScrapingTool(Enum):
    SCRAPGRAPHAI = "scrapgraphai"
    FIRECRAWL = "firecrawl"
    CRAWLFORAI = "crawlforai"
    MEGAPARSER = "megaparser"
    LLAMAPARSE = "llamaparse"
    EXTRACTTHINKER = "extractthinker"
    DOCLINK = "doclink"

@dataclass
class Lead:
    id: str
    first_name: str
    last_name: str
    company_name: str
    industry: str
    position: str
    email: str
    phone: Optional[str] = None
    company_website: Optional[str] = None
    company_description: Optional[str] = None
    company_size: Optional[str] = None
    location: Optional[str] = None
    linkedin_profile: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    scraping_tool_used: Optional[ScrapingTool] = None
    metadata: Dict = field(default_factory=dict)
    
    def get_formal_greeting(self) -> str:
        """Generate formal greeting based on lead information"""
        if self.position and "manager" in self.position.lower():
            return f"Dear Manager,"
        elif self.position:
            return f"Dear {self.position},"
        else:
            return f"Dear {self.company_name} Team,"
    
    def generate_outreach_email(self, tone: EmailTone = EmailTone.FORMAL, 
                               subject: Optional[str] = None,
                               company_pain_points: Optional[List[str]] = None) -> Dict[str, str]:
        """
        Generate industry-specific, company-specific outreach email
        
        Args:
            tone: Email tone/style
            subject: Custom subject line
            company_pain_points: Specific pain points for personalization
            
        Returns:
            Dict with 'subject' and 'body' keys
        """
        greeting = self.get_formal_greeting()
        
        # Industry-specific templates would be implemented here
        # This is a placeholder structure
        email_body = self._compose_email_body(tone, company_pain_points)
        
        if not subject:
            subject = self._generate_subject(tone)
        
        return {
            "subject": subject,
            "body": f"{greeting}\n\n{email_body}",
            "tone": tone.value,
            "recipient": {
                "name": f"{self.first_name} {self.last_name}",
                "email": self.email,
                "company": self.company_name
            }
        }
    
    def _compose_email_body(self, tone: EmailTone, pain_points: Optional[List[str]]) -> str:
        """Compose personalized email body based on industry and tone"""
        # This would be enhanced with actual industry-specific logic
        body_template = f"""I noticed {self.company_name} operates in the {self.industry} sector."""
        
        if pain_points:
            body_template += f"\n\nI understand you may be facing challenges with: {', '.join(pain_points)}"
        
        body_template += "\n\nI'd like to discuss how we can help you achieve your goals."
        body_template += "\n\nBest regards"
        
        return body_template
    
    def _generate_subject(self, tone: EmailTone) -> str:
        """Generate tone-appropriate subject line"""
        subjects = {
            EmailTone.PROFESSIONAL: f"Partnership Opportunity - {self.company_name}",
            EmailTone.FORMAL: f"Inquiry: How {self.company_name} Can Benefit",
            EmailTone.CASUAL: f"Quick thought about {self.company_name}",
            EmailTone.URGENT: f"Time-Sensitive: Growth Opportunity for {self.company_name}",
            EmailTone.FRIENDLY: f"Let's connect, {self.first_name}!"
        }
        return subjects.get(tone, f"Partnership Opportunity - {self.company_name}")
