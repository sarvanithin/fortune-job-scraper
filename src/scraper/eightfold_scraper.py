"""
Eightfold AI career site scraper.
Handles sites like aexp.eightfold.ai, prudential.eightfold.ai, etc.

Eightfold uses a React-based SPA that loads jobs dynamically via API.
"""
import asyncio
import json
import re
from typing import List, Optional
from urllib.parse import urljoin, urlparse, parse_qs

from playwright.async_api import async_playwright, Page, Browser, TimeoutError as PlaywrightTimeout

from config import (
    SCRAPE_DELAY_SECONDS,
    PAGE_LOAD_TIMEOUT_MS,
    MAX_PAGES_PER_COMPANY,
)
from scraper.base_scraper import BaseScraper, Job


class EightfoldScraper(BaseScraper):
    """
    Specialized scraper for Eightfold AI career sites.
    These sites use a consistent React-based UI.
    """

    # Eightfold-specific selectors
    JOB_CARD_SELECTORS = [
        # Primary job card selectors
        '[data-test-id="position-card"]',
        '[class*="position-card"]',
        '[class*="PositionCard"]',
        'a[href*="/position/"]',
        'a[href*="/job/"]',
        # Job list items
        '[class*="job-card"]',
        '[class*="JobCard"]',
        'div[role="listitem"] a',
        # List-based layouts
        'ul[class*="position"] li a',
        'div[class*="positions-list"] a',
        # Generic fallbacks
        'main a[href*="position"]',
        'section a[href*="job"]',
    ]

    TITLE_SELECTORS = [
        '[data-test-id="position-title"]',
        '[class*="position-title"]',
        '[class*="PositionTitle"]',
        'h2',
        'h3',
        '[class*="title"]',
        '[class*="Title"]',
    ]

    LOCATION_SELECTORS = [
        '[data-test-id="position-location"]',
        '[class*="position-location"]',
        '[class*="PositionLocation"]',
        '[class*="location"]',
        '[class*="Location"]',
    ]

    PAGINATION_SELECTORS = [
        'button[aria-label*="next" i]',
        'button[aria-label*="Next" i]',
        'a[aria-label*="next" i]',
        '[data-test-id="pagination-next"]',
        'button:has-text("Next")',
        'a:has-text("Next")',
        '[class*="pagination"] button:last-child',
        '[class*="Pagination"] button:last-child',
    ]

    LOAD_MORE_SELECTORS = [
        'button:has-text("Load more")',
        'button:has-text("Show more")',
        'button:has-text("View more")',
        '[data-test-id="load-more"]',
        '[class*="load-more"]',
        '[class*="loadMore"]',
    ]

    def __init__(self, company_name: str, career_url: str):
        super().__init__(company_name, career_url)
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        self.seen_urls: set = set()

    async def scrape(self) -> List[Job]:
        """Scrape all job listings from Eightfold career page."""
        all_jobs: List[Job] = []

        async with async_playwright() as p:
            self.browser = await p.chromium.launch(
                headless=True,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--disable-dev-shm-usage',
                    '--no-sandbox',
                ]
            )

            context = await self.browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            )

            self.page = await context.new_page()

            try:
                print(f"  [Eightfold] Navigating to {self.career_url}")
                
                # Navigate with longer timeout for SPAs
                await self.page.goto(
                    self.career_url,
                    wait_until='networkidle',
                    timeout=PAGE_LOAD_TIMEOUT_MS * 2,
                )
                
                # Wait extra time for React to render
                await asyncio.sleep(5)
                
                # Try to scroll to load all content
                await self._scroll_to_load_all()

                # Scrape pages
                page_count = 0
                while page_count < MAX_PAGES_PER_COMPANY:
                    page_count += 1
                    print(f"  [Eightfold] Scraping page {page_count} for {self.company_name}...")

                    # Extract jobs from current page
                    page_jobs = await self._extract_jobs()
                    
                    # Check for new jobs
                    new_jobs_count = 0
                    for job in page_jobs:
                        if job.job_url not in self.seen_urls:
                            self.seen_urls.add(job.job_url)
                            all_jobs.append(job)
                            new_jobs_count += 1
                    
                    print(f"    Found {new_jobs_count} new jobs on page {page_count}")

                    if new_jobs_count == 0 and page_count > 1:
                        print(f"  [Eightfold] No new jobs found, stopping pagination")
                        break

                    # Try load more / pagination
                    has_more = await self._handle_pagination()
                    if not has_more:
                        break

                    await asyncio.sleep(SCRAPE_DELAY_SECONDS)

            except Exception as e:
                print(f"  [Eightfold] Error scraping {self.company_name}: {e}")

            finally:
                await self.browser.close()

        # Filter by keywords
        filtered_jobs = []
        for job in all_jobs:
            matched_keywords = self.matches_keywords(job.job_title)
            if matched_keywords:
                job.keywords_matched = matched_keywords
                filtered_jobs.append(job)

        print(f"  [Eightfold] Found {len(filtered_jobs)} matching jobs (out of {len(all_jobs)} total)")
        return filtered_jobs

    async def _scroll_to_load_all(self):
        """Scroll down to trigger lazy loading of content."""
        try:
            for _ in range(5):
                await self.page.evaluate('window.scrollBy(0, window.innerHeight)')
                await asyncio.sleep(1)
            
            # Scroll back to top
            await self.page.evaluate('window.scrollTo(0, 0)')
            await asyncio.sleep(1)
        except Exception:
            pass

    async def _extract_jobs(self) -> List[Job]:
        """Extract jobs from current page."""
        jobs: List[Job] = []

        # Try each job card selector
        for selector in self.JOB_CARD_SELECTORS:
            try:
                elements = await self.page.query_selector_all(selector)
                if elements:
                    print(f"    Found {len(elements)} elements with selector: {selector}")
                    
                    for element in elements:
                        job = await self._parse_job_card(element)
                        if job:
                            jobs.append(job)
                    
                    if jobs:
                        break  # Found jobs with this selector
            except Exception as e:
                continue

        # If no jobs found, try extracting from all links
        if not jobs:
            jobs = await self._extract_jobs_from_links()

        return jobs

    async def _parse_job_card(self, element) -> Optional[Job]:
        """Parse a job card element."""
        try:
            # Get href - might be on element or need to find child link
            href = await element.get_attribute('href')
            
            if not href:
                # Try finding a link within the element
                link = await element.query_selector('a[href]')
                if link:
                    href = await link.get_attribute('href')
            
            if not href or href.startswith('#') or 'javascript:' in href:
                return None

            job_url = self.normalize_url(href)
            
            # Skip if not a job URL
            if not any(x in job_url.lower() for x in ['/position/', '/job/', '/careers/']):
                return None

            # Get title - try multiple approaches
            title = ""
            for title_sel in self.TITLE_SELECTORS:
                try:
                    title_el = await element.query_selector(title_sel)
                    if title_el:
                        title = await title_el.text_content()
                        title = self.clean_text(title)
                        if title and len(title) > 3:
                            break
                except Exception:
                    continue
            
            # Fallback to element text
            if not title:
                title = await element.text_content()
                title = self.clean_text(title) if title else ""
            
            if not title or len(title) < 3:
                return None

            # Get location
            location = ""
            for loc_sel in self.LOCATION_SELECTORS:
                try:
                    loc_el = await element.query_selector(loc_sel)
                    if loc_el:
                        location = await loc_el.text_content()
                        location = self.clean_text(location) if location else ""
                        break
                except Exception:
                    continue

            # Generate job ID
            job_id = self._extract_eightfold_job_id(job_url) or self.generate_job_id(job_url, title)

            return Job(
                job_id=job_id,
                job_title=title,
                job_url=job_url,
                company_name=self.company_name,
                company_career_url=self.career_url,
                location=location,
            )

        except Exception as e:
            return None

    async def _extract_jobs_from_links(self) -> List[Job]:
        """Fallback: Extract jobs by finding all position/job links."""
        jobs: List[Job] = []

        try:
            # Find all links that look like job postings
            links = await self.page.query_selector_all('a[href*="position"], a[href*="job"]')
            
            for link in links:
                href = await link.get_attribute('href')
                if not href:
                    continue
                    
                job_url = self.normalize_url(href)
                
                # Skip non-job URLs
                if not any(x in job_url.lower() for x in ['/position/', '/job/']):
                    continue
                if any(x in job_url.lower() for x in ['/login', '/apply', '/saved']):
                    continue

                title = await link.text_content()
                title = self.clean_text(title) if title else ""
                
                if not title or len(title) < 3 or len(title) > 200:
                    continue

                job_id = self._extract_eightfold_job_id(job_url) or self.generate_job_id(job_url, title)
                
                jobs.append(Job(
                    job_id=job_id,
                    job_title=title,
                    job_url=job_url,
                    company_name=self.company_name,
                    company_career_url=self.career_url,
                ))

        except Exception as e:
            print(f"    Error extracting from links: {e}")

        return jobs

    def _extract_eightfold_job_id(self, url: str) -> Optional[str]:
        """Extract Eightfold position ID from URL."""
        patterns = [
            r'/position/([A-Za-z0-9_-]+)',
            r'/job/([A-Za-z0-9_-]+)',
            r'positionId=([A-Za-z0-9_-]+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return f"EF_{match.group(1)}"
        return None

    async def _handle_pagination(self) -> bool:
        """Handle Eightfold pagination or load more buttons."""
        
        # First try "Load More" buttons
        for selector in self.LOAD_MORE_SELECTORS:
            try:
                button = await self.page.query_selector(selector)
                if button:
                    is_visible = await button.is_visible()
                    is_disabled = await button.get_attribute('disabled')
                    
                    if is_visible and not is_disabled:
                        await button.click()
                        await asyncio.sleep(3)  # Wait for content to load
                        return True
            except Exception:
                continue

        # Then try pagination buttons
        for selector in self.PAGINATION_SELECTORS:
            try:
                button = await self.page.query_selector(selector)
                if button:
                    is_visible = await button.is_visible()
                    is_disabled = await button.get_attribute('disabled')
                    aria_disabled = await button.get_attribute('aria-disabled')
                    
                    if is_visible and not is_disabled and aria_disabled != 'true':
                        await button.click()
                        await self.page.wait_for_load_state('networkidle', timeout=10000)
                        await asyncio.sleep(2)
                        return True
            except Exception:
                continue

        # Try infinite scroll
        try:
            old_height = await self.page.evaluate('document.body.scrollHeight')
            await self.page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            await asyncio.sleep(2)
            new_height = await self.page.evaluate('document.body.scrollHeight')
            
            if new_height > old_height:
                return True
        except Exception:
            pass

        return False
