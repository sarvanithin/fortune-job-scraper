"""
Dispatcher that routes URLs to the appropriate scraper based on platform detection.
"""
from typing import Type, Optional
from urllib.parse import urlparse

from config import WORKDAY_PATTERNS, EIGHTFOLD_PATTERNS
from scraper.base_scraper import BaseScraper
from scraper.generic_scraper import GenericScraper
from scraper.workday_scraper import WorkdayScraper
from scraper.eightfold_scraper import EightfoldScraper


class ScraperDispatcher:
    """Routes career URLs to the appropriate platform-specific scraper."""

    @staticmethod
    def detect_platform(url: str) -> str:
        """
        Detect the career platform from URL patterns.

        Returns:
            Platform name: 'workday', 'eightfold', or 'generic'
        """
        url_lower = url.lower()

        for pattern in WORKDAY_PATTERNS:
            if pattern in url_lower:
                return 'workday'

        for pattern in EIGHTFOLD_PATTERNS:
            if pattern in url_lower:
                return 'eightfold'

        return 'generic'

    @staticmethod
    def get_scraper(
        company_name: str,
        career_url: str,
        platform_hint: Optional[str] = None,
    ) -> BaseScraper:
        """
        Get the appropriate scraper for a given career URL.

        Args:
            company_name: Company name for context.
            career_url: The career page URL to scrape.
            platform_hint: Optional hint about the platform type.

        Returns:
            Appropriate scraper instance.
        """
        # Use hint if provided, otherwise detect
        platform = platform_hint or ScraperDispatcher.detect_platform(career_url)

        print(f"Using {platform} scraper for {company_name}")

        if platform == 'workday':
            return WorkdayScraper(company_name, career_url)
        elif platform == 'eightfold':
            return EightfoldScraper(company_name, career_url)
        else:
            return GenericScraper(company_name, career_url)

