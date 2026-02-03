"""
Eightfold AI career site scraper.
Handles sites like aexp.eightfold.ai, prudential.eightfold.ai, etc.

Eightfold uses a React-based SPA that loads jobs dynamically.
This scraper uses extensive selectors to find job listings in various layouts.
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
    These sites use a consistent React-based UI with left sidebar job list.
    """

    # Eightfold job card selectors - comprehensive list based on common patterns
    JOB_CARD_SELECTORS = [
        # Primary selectors for sidebar job list (AmEx style)
        'div[class*="positions"] > div[class*="position"]',
        'div[class*="position-cards"] > div',
        'div[class*="position-list"] a',
        'div[class*="jobs-list"] > div',
        'div[class*="job-list"] > div',
        '[data-test-id="position-card"]',
        '[class*="PositionCard"]',
        '[class*="position-card"]',
        # Left sidebar patterns
        'aside a[href*="/position/"]',
        'nav[role="navigation"] a[href*="/position/"]',
        'div[role="list"] a[href*="/position/"]',
        'div[role="listbox"] div[role="option"]',
        # List items
        'ul[class*="position"] > li',
        'ul[class*="jobs"] > li',
        'ul[class*="results"] > li',
        'article[class*="position"]',
        'article[class*="job"]',
        # Card patterns
        '[class*="job-card"]',
        '[class*="JobCard"]',
        '[class*="search-result"]',
        '[class*="SearchResult"]',
        # Links to positions
        'a[href*="/position/"]',
        'a[href*="/job/"]',
        'a[href*="/careers/"][href*="position"]',
        # Generic wrappers
        'main a[href*="position"]',
        'section a[href*="position"]',
        'div[class*="results"] a',
        # AmEx-specific patterns based on screenshot
        'div[class*="search-results"] > div',
        'div[class*="SearchResults"] > div',
        'div[class*="job-search"] a',
    ]

    TITLE_SELECTORS = [
        '[data-test-id="position-title"]',
        '[class*="position-title"]',
        '[class*="PositionTitle"]',
        '[class*="job-title"]',
        '[class*="JobTitle"]',
        'h2[class*="title"]',
        'h3[class*="title"]',
        'h4[class*="title"]',
        'span[class*="title"]',
        'div[class*="title"]',
        'a[class*="title"]',
        'h2', 'h3', 'h4',
        '[class*="Title"]',
        'strong',
    ]

    LOCATION_SELECTORS = [
        '[data-test-id="position-location"]',
        '[class*="position-location"]',
        '[class*="PositionLocation"]',
        '[class*="job-location"]',
        '[class*="JobLocation"]',
        '[class*="location"]',
        '[class*="Location"]',
        'span[class*="geo"]',
        'div[class*="address"]',
    ]

    PAGINATION_SELECTORS = [
        'button[aria-label*="next" i]',
        'button[aria-label*="Next" i]',
        'a[aria-label*="next" i]',
        '[data-test-id="pagination-next"]',
        'button:has-text("Next")',
        'a:has-text("Next")',
        '[class*="pagination"] button:not([disabled]):last-child',
        '[class*="Pagination"] button:not([disabled]):last-child',
        'nav[aria-label*="pagination"] a:last-child',
    ]

    LOAD_MORE_SELECTORS = [
        'button:has-text("Load more")',
        'button:has-text("Show more")',
        'button:has-text("View more")',
        'button:has-text("See more")',
        '[data-test-id="load-more"]',
        '[class*="load-more"]',
        '[class*="loadMore"]',
        '[class*="show-more"]',
    ]

    def __init__(self, company_name: str, career_url: str):
        super().__init__(company_name, career_url)
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        self.seen_urls: set = set()
        self.seen_titles: set = set()

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
                
                # Navigate with extended timeout for SPAs
                await self.page.goto(
                    self.career_url,
                    wait_until='networkidle',
                    timeout=PAGE_LOAD_TIMEOUT_MS * 2,
                )
                
                # Wait for React to fully render (Eightfold is slow)
                print(f"  [Eightfold] Waiting for React to render...")
                await asyncio.sleep(8)
                
                # Scroll to trigger lazy loading
                await self._scroll_to_load_all()

                # Try multiple extraction strategies
                print(f"  [Eightfold] Extracting jobs using multiple strategies...")
                
                # Strategy 1: Direct job card extraction
                jobs = await self._extract_jobs()
                
                # Strategy 2: If no jobs found, try link-based extraction
                if not jobs:
                    print(f"  [Eightfold] Trying link-based extraction...")
                    jobs = await self._extract_jobs_from_links()
                
                # Strategy 3: Try extracting from visible text with job-like patterns
                if not jobs:
                    print(f"  [Eightfold] Trying text-based extraction...")
                    jobs = await self._extract_jobs_from_text()
                
                all_jobs.extend(jobs)
                
                # Handle pagination/infinite scroll for additional pages
                page_count = 1
                while page_count < MAX_PAGES_PER_COMPANY:
                    has_more = await self._handle_pagination()
                    if not has_more:
                        break
                    
                    page_count += 1
                    print(f"  [Eightfold] Scraping page {page_count}...")
                    await asyncio.sleep(3)
                    
                    new_jobs = await self._extract_jobs()
                    new_count = 0
                    for job in new_jobs:
                        if job.job_url not in self.seen_urls:
                            self.seen_urls.add(job.job_url)
                            all_jobs.append(job)
                            new_count += 1
                    
                    if new_count == 0:
                        break
                    
                    print(f"    Found {new_count} new jobs on page {page_count}")

            except Exception as e:
                print(f"  [Eightfold] Error: {e}")

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
        """Scroll down to trigger lazy loading of job list."""
        try:
            print(f"  [Eightfold] Scrolling to load all content...")
            
            # Scroll the page multiple times
            for i in range(8):
                await self.page.evaluate('window.scrollBy(0, window.innerHeight)')
                await asyncio.sleep(0.8)
            
            # Try to find and scroll within a job list container
            containers = [
                'div[class*="position-list"]',
                'div[class*="jobs-list"]',
                'div[class*="search-results"]',
                'aside',
                'nav[role="navigation"]',
            ]
            
            for container_sel in containers:
                try:
                    container = await self.page.query_selector(container_sel)
                    if container:
                        # Scroll inside the container
                        for _ in range(5):
                            await container.evaluate('el => el.scrollTop += 500')
                            await asyncio.sleep(0.5)
                        break
                except Exception:
                    continue
            
            # Scroll back to top
            await self.page.evaluate('window.scrollTo(0, 0)')
            await asyncio.sleep(1)
            
        except Exception as e:
            pass

    async def _extract_jobs(self) -> List[Job]:
        """Extract jobs using card selectors."""
        jobs: List[Job] = []

        for selector in self.JOB_CARD_SELECTORS:
            try:
                elements = await self.page.query_selector_all(selector)
                if not elements:
                    continue
                
                for element in elements:
                    job = await self._parse_job_card(element)
                    if job and job.job_url not in self.seen_urls and job.job_title not in self.seen_titles:
                        self.seen_urls.add(job.job_url)
                        self.seen_titles.add(job.job_title)
                        jobs.append(job)
                
                if jobs:
                    print(f"    Found {len(jobs)} jobs with selector: {selector[:50]}...")
                    break  # Found jobs, stop trying other selectors
                    
            except Exception:
                continue

        return jobs

    async def _parse_job_card(self, element) -> Optional[Job]:
        """Parse a job card element."""
        try:
            # Get href - check element first, then look for child links
            href = await element.get_attribute('href')
            
            if not href:
                link = await element.query_selector('a[href]')
                if link:
                    href = await link.get_attribute('href')
            
            if not href or href.startswith('#') or 'javascript:' in href:
                return None

            job_url = self.normalize_url(href)
            
            # Must be a job URL
            if not any(x in job_url.lower() for x in ['/position/', '/job/', '/careers/', 'intlink=']):
                return None
            
            # Skip utility links
            if any(x in job_url.lower() for x in ['/login', '/apply/', '/saved', '/share']):
                return None

            # Get title - try several methods
            title = await self._extract_title(element)
            
            if not title or len(title) < 3 or len(title) > 200:
                return None

            # Get location
            location = await self._extract_location(element)

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

        except Exception:
            return None

    async def _extract_title(self, element) -> str:
        """Extract job title from element."""
        for title_sel in self.TITLE_SELECTORS:
            try:
                title_el = await element.query_selector(title_sel)
                if title_el:
                    title = await title_el.text_content()
                    title = self.clean_text(title) if title else ""
                    if title and len(title) > 3 and len(title) < 200:
                        return title
            except Exception:
                continue
        
        # Fallback: use element's own text
        try:
            title = await element.text_content()
            title = self.clean_text(title) if title else ""
            # If text is too long, try to get first line
            if title and len(title) > 200:
                title = title.split('\n')[0].strip()
            return title if title and len(title) > 3 else ""
        except Exception:
            return ""

    async def _extract_location(self, element) -> str:
        """Extract location from element."""
        for loc_sel in self.LOCATION_SELECTORS:
            try:
                loc_el = await element.query_selector(loc_sel)
                if loc_el:
                    location = await loc_el.text_content()
                    location = self.clean_text(location) if location else ""
                    if location and len(location) < 100:
                        return location
            except Exception:
                continue
        return ""

    async def _extract_jobs_from_links(self) -> List[Job]:
        """Fallback: Extract jobs by finding all position/job links."""
        jobs: List[Job] = []

        try:
            # Find all links that look like job postings
            link_selectors = [
                'a[href*="/position/"]',
                'a[href*="/job/"]',
                'a[href*="intlink="]',
                'a[href*="positionId="]',
            ]
            
            for sel in link_selectors:
                links = await self.page.query_selector_all(sel)
                
                for link in links:
                    href = await link.get_attribute('href')
                    if not href:
                        continue
                        
                    job_url = self.normalize_url(href)
                    
                    # Skip non-job URLs
                    if any(x in job_url.lower() for x in ['/login', '/apply/', '/saved', '/share']):
                        continue

                    if job_url in self.seen_urls:
                        continue

                    title = await link.text_content()
                    title = self.clean_text(title) if title else ""
                    
                    if not title or len(title) < 5 or len(title) > 200:
                        continue
                    
                    if title in self.seen_titles:
                        continue

                    self.seen_urls.add(job_url)
                    self.seen_titles.add(title)

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

    async def _extract_jobs_from_text(self) -> List[Job]:
        """Last resort: extract jobs by looking for job-like text patterns."""
        jobs: List[Job] = []
        
        try:
            # Look for elements containing job-related text
            text_selectors = [
                'div:has-text("Manager")',
                'div:has-text("Director")',
                'div:has-text("Engineer")',
                'div:has-text("Analyst")',
                'div:has-text("Scientist")',
            ]
            
            for sel in text_selectors:
                try:
                    elements = await self.page.query_selector_all(sel)
                    for el in elements[:50]:  # Limit to avoid too many
                        # Look for a link nearby
                        link = await el.query_selector('a[href]')
                        if link:
                            href = await link.get_attribute('href')
                            if href and '/position/' in href:
                                title = await el.text_content()
                                title = self.clean_text(title)
                                if title and len(title) > 5 and len(title) < 150:
                                    job_url = self.normalize_url(href)
                                    if job_url not in self.seen_urls:
                                        self.seen_urls.add(job_url)
                                        job_id = self.generate_job_id(job_url, title)
                                        jobs.append(Job(
                                            job_id=job_id,
                                            job_title=title,
                                            job_url=job_url,
                                            company_name=self.company_name,
                                            company_career_url=self.career_url,
                                        ))
                except Exception:
                    continue
                
        except Exception:
            pass
        
        return jobs

    def _extract_eightfold_job_id(self, url: str) -> Optional[str]:
        """Extract Eightfold position ID from URL."""
        patterns = [
            r'/position/([A-Za-z0-9_-]+)',
            r'/job/([A-Za-z0-9_-]+)',
            r'positionId=([A-Za-z0-9_-]+)',
            r'intlink=([^&]+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return f"EF_{match.group(1)[:20]}"  # Truncate long IDs
        return None

    async def _handle_pagination(self) -> bool:
        """Handle pagination or load more buttons."""
        
        # First try "Load More" buttons
        for selector in self.LOAD_MORE_SELECTORS:
            try:
                button = await self.page.query_selector(selector)
                if button:
                    is_visible = await button.is_visible()
                    is_disabled = await button.get_attribute('disabled')
                    
                    if is_visible and not is_disabled:
                        await button.click()
                        await asyncio.sleep(3)
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
