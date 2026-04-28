class LeadGenBaseError(Exception):
    """Base for all domain errors."""


class DiscoveryError(LeadGenBaseError):
    """Raised when Google Maps scraping fails."""


class EnrichmentError(LeadGenBaseError):
    """Raised when website enrichment fails."""


class ICPEvaluationError(LeadGenBaseError):
    """Raised when ICP scoring fails."""


class OutreachGenerationError(LeadGenBaseError):
    """Raised when LLM outreach draft generation fails."""


class StorageError(LeadGenBaseError):
    """Raised on DB read/write failures."""
