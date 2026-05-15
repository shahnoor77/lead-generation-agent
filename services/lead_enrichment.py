import asyncio
import logging
from typing import List
from models.lead import Lead, Industry, EmailTone
from services.scraping_orchestrator import ScrapingOrchestrator
from services.email_generator import EmailGenerator

logger = logging.getLogger(__name__)

class LeadEnrichment:
    def __init__(self):
        self.scraper = ScrapingOrchestrator()
        self.email_generator = EmailGenerator()

    async def enrich_and_generate_emails(
        self,
        leads: List[Lead],
        tone: EmailTone = EmailTone.FORMAL,
        sender_name: str = "Your Company",
        sender_title: str = "Business Development",
    ) -> List[dict]:
        """Enrich leads with scraped data and generate personalized emails."""
        
        results = []
        
        for lead in leads:
            try:
                # Scrape company website for additional data
                enriched_lead = await self._enrich_lead(lead)
                
                # Generate industry and company-specific email
                email = self.email_generator.generate_email(
                    enriched_lead,
                    tone=tone,
                    sender_name=sender_name,
                    sender_title=sender_title
                )
                
                results.append({
                    "lead": enriched_lead,
                    "email": email,
                    "status": "success"
                })
                
            except Exception as e:
                logger.error(f"Failed to process lead {lead.company_name}: {e}")
                results.append({
                    "lead": lead,
                    "email": None,
                    "status": "failed",
                    "error": str(e)
                })
        
        return results

    async def _enrich_lead(self, lead: Lead) -> Lead:
        """Scrape and enrich lead data."""
        
        extraction_schema = {
            "required_fields": ["company_description", "contacts", "company_info"],
            "fields": {
                "company_description": "Company overview and mission",
                "company_size": "Number of employees",
                "contacts": "Key contacts with titles and emails",
                "focus_areas": "Main business focus areas",
                "social_media": "Social media links",
            }
        }
        
        scraped_data = await self.scraper.scrape_with_fallback(
            lead.website,
            extraction_schema
        )
        
        if scraped_data:
            if "company_description" in scraped_data:
                lead.description = scraped_data["company_description"]
            
            if "company_size" in scraped_data:
                lead.company_size = scraped_data["company_size"]
            
            if "contacts" in scraped_data and isinstance(scraped_data["contacts"], list):
                primary_contact = scraped_data["contacts"][0]
                lead.contact_name = primary_contact.get("name")
                lead.contact_title = primary_contact.get("title")
                lead.contact_email = primary_contact.get("email")
            
            if "focus_areas" in scraped_data:
                lead.tags = scraped_data["focus_areas"]
            
            lead.raw_data = scraped_data
        
        return lead
