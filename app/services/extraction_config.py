"""
Configuration for extraction and email services.
Centralizes provider priorities, retry logic, and defaults.
"""

from enum import Enum
from dataclasses import dataclass

__all__ = ["ExtractionProvider", "extraction_config"]


class ExtractionProvider(str, Enum):
    """Available extraction providers (in priority order)."""
    SCRAPGRAPH = "scrapgraph"
    FIRECRAWL = "firecrawl"
    CRAWLFORAI = "crawlforai"
    LLAMAPARSE = "llamaparse"
    FALLBACK = "fallback"


@dataclass
class ExtractionConfig:
    """Configuration for multi-source extraction."""
    # Priority order for providers
    provider_priority: list[ExtractionProvider] = None
    
    # Retry settings
    max_retries: int = 2
    timeout_seconds: int = 30
    
    # Quality thresholds
    min_content_length: int = 100
    
    # Provider-specific settings
    enable_scrapgraph: bool = True
    enable_firecrawl: bool = True
    enable_crawlforai: bool = True
    enable_llamaparse: bool = True
    
    def __post_init__(self):
        if self.provider_priority is None:
            self.provider_priority = [
                ExtractionProvider.SCRAPGRAPH,
                ExtractionProvider.FIRECRAWL,
                ExtractionProvider.CRAWLFORAI,
                ExtractionProvider.LLAMAPARSE,
                ExtractionProvider.FALLBACK,
            ]


# Global config instance
extraction_config = ExtractionConfig()
