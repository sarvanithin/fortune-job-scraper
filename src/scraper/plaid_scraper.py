"""
Plaid careers page scraper.
Handles plaid.com/careers - a React/Next.js site with unique job card structure.

Based on screenshot analysis:
- Jobs shown as cards with location on top, title below
- "See role" buttons link to job details
- Hash-based URL navigation (#search)
- Department sections (Engineering, etc.)
"""
import asyncio
import re
from typing import List, Optional

from playwright.async_api import async_playwright, Page, Browser

from config import PAGE_LOAD_TIMEOUT_MS, SCRAPE_DELAY_SECONDS
from scraper.base_scraper import BaseScraper, Job


class PlaidScraper(BaseScraper):
    """
    Specialized scraper for Plaid's careers page.
    Plaid uses a custom Next.js site with job cards and "See role" buttons.
    """

    # Plaid-specific selectors based on screenshot structure
    JOB_CARD_SELECTORS = [
        # Job card containers (each card has location + title)
        'a[href*="/careers/openings/"]',
        'div[class*="job-card"]',
        'div[class*="opening"]',
        'article[class*="job"]',
        'article[class*="role"]',
        # List items that look like jobs
        'li:has(a[href*="/careers/"])',
        'div:has(> a:has-text("See role"))',
        # Cards with role buttons
        '[class*="role-card"]',
        '[class*="RoleCard"]',
        '[class*="position-card"]',
        # Generic patterns
        'main a[href*="/openings/"]',
        'section a[href*="/careers/openings/"]',
    ]

    # Selectors for finding "See role" type links
    ROLE_LINK_SELECTORS = [
        'a:has-text("See role")',
        'a:has-text("Apply")',
        'a:has-text("View")',
        'a[href*="/openings/"]',
        'a[href*="/careers/"][href*="/"]',
    ]

    TITLE_SELECTORS = [
        'h2', 'h3', 'h4',
        '[class*="title"]',
        '[class*="Title"]',
        '[class*="role-name"]',
        '[class*="job-name"]',
        'strong',
        'span[class*="name"]',
    ]

    LOCATION_SELECTORS = [
        '[class*="location"]',
        '[class*="Location"]',
        'span:has-text("New York")',
        'span:has-text("San Francisco")',
        'span:has-text("Remote")',
        'div[class*="meta"]',
        'p[class*="location"]',
    ]

    def __init__(self, company_name: str, career_url: str):
        super().__init__(company_name, career_url)
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        self.seen_urls: set = set()
        self.seen_titles: set = set()

    async def scrape(self) -> List[Job]:
        """Scrape all job listings from Plaid's careers page."""
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
                print(f"  [Plaid] Navigating to {self.career_url}")
                
                await self.page.goto(
                    self.career_url,
                    wait_until='networkidle',
                    timeout=PAGE_LOAD_TIMEOUT_MS,
                )
                
                # Wait for React to render
                print(f"  [Plaid] Waiting for React to render...")
                await asyncio.sleep(5)
                
                # Handle cookie consent if present
                await self._dismiss_cookie_banner()
                
                # Scroll to load all content
                await self._scroll_to_load_all()

                # Extract jobs using multiple strategies
                print(f"  [Plaid] Extracting jobs...")
                
                # Strategy 1: Find "See role" links and parent cards
                jobs = await self._extract_jobs_from_role_links()
                
                # Strategy 2: Find job cards directly
                if not jobs:
                    jobs = await self._extract_jobs_from_cards()
                
                # Strategy 3: Find all career opening links
                if not jobs:
                    jobs = await self._extract_jobs_from_links()
                
                all_jobs.extend(jobs)

            except Exception as e:
                print(f"  [Plaid] Error: {e}")

            finally:
                await self.browser.close()

        # Filter by keywords
        filtered_jobs = []
        for job in all_jobs:
            matched_keywords = self.matches_keywords(job.job_title)
            if matched_keywords:
                job.keywords_matched = matched_keywords
                filtered_jobs.append(job)

        print(f"  [Plaid] Found {len(filtered_jobs)} matching jobs (out of {len(all_jobs)} total)")
        return filtered_jobs

    async def _dismiss_cookie_banner(self):
        """Try to dismiss any cookie banners."""
        try:
            cookie_selectors = [
                'button:has-text("Ok")',
                'button:has-text("Accept")',
                'button:has-text("Got it")',
                '[class*="cookie"] button',
                '[class*="consent"] button',
            ]
            for sel in cookie_selectors:
                btn = await self.page.query_selector(sel)
                if btn and await btn.is_visible():
                    await btn.click()
                    await asyncio.sleep(1)
                    break
        except Exception:
            pass

    async def _scroll_to_load_all(self):
        """Scroll to load all job content."""
        try:
            print(f"  [Plaid] Scrolling to load content...")
            for _ in range(10):
                await self.page.evaluate('window.scrollBy(0, window.innerHeight)')
                await asyncio.sleep(0.5)
            
            # Scroll back to top
            await self.page.evaluate('window.scrollTo(0, 0)')
            await asyncio.sleep(1)
        except Exception:
            pass

    async def _extract_jobs_from_role_links(self) -> List[Job]:
        """Extract jobs by finding 'See role' links and getting parent card info."""
        jobs: List[Job] = []
        
        try:
            for link_sel in self.ROLE_LINK_SELECTORS:
                links = await self.page.query_selector_all(link_sel)
                
                for link in links:
                    try:
                        href = await link.get_attribute('href')
                        if not href:
                            continue
                        
                        job_url = self.normalize_url(href)
                        
                        # Must be a careers URL
                        if '/careers/' not in job_url and '/openings/' not in job_url:
                            continue
                        
                        if job_url in self.seen_urls:
                            continue
                        
                        # Get the parent container for title and location
                        parent = await link.evaluate_handle('el => el.closest("div, article, section, li")')
                        
                        title = ""
                        location = ""
                        
                        if parent:
                            # Extract title from parent
                            for title_sel in self.TITLE_SELECTORS:
                                try:
                                    title_el = await parent.query_selector(title_sel)
                                    if title_el:
                                        text = await title_el.text_content()
                                        text = self.clean_text(text) if text else ""
                                        # Skip if it's the button text
                                        if text and text.lower() not in ['see role', 'apply', 'view']:
                                            if len(text) > 5 and len(text) < 150:
                                                title = text
                                                break
                                except Exception:
                                    continue
                            
                            # Extract location from parent
                            for loc_sel in self.LOCATION_SELECTORS:
                                try:
                                    loc_el = await parent.query_selector(loc_sel)
                                    if loc_el:
                                        location = await loc_el.text_content()
                                        location = self.clean_text(location) if location else ""
                                        break
                                except Exception:
                                    continue
                        
                        # If no title from parent, try from URL
                        if not title:
                            title = self._extract_title_from_url(job_url)
                        
                        if not title or len(title) < 3:
                            continue
                        
                        if title in self.seen_titles:
                            continue
                        
                        self.seen_urls.add(job_url)
                        self.seen_titles.add(title)
                        
                        job_id = self._extract_plaid_job_id(job_url)
                        
                        jobs.append(Job(
                            job_id=job_id,
                            job_title=title,
                            job_url=job_url,
                            company_name=self.company_name,
                            company_career_url=self.career_url,
                            location=location,
                        ))
                        
                    except Exception:
                        continue
                
                if jobs:
                    print(f"    Found {len(jobs)} jobs using selector: {link_sel[:30]}...")
                    break
                    
        except Exception as e:
            print(f"    Error in role link extraction: {e}")
        
        return jobs

    async def _extract_jobs_from_cards(self) -> List[Job]:
        """Extract jobs from card elements."""
        jobs: List[Job] = []
        
        for card_sel in self.JOB_CARD_SELECTORS:
            try:
                cards = await self.page.query_selector_all(card_sel)
                
                for card in cards:
                    # Check if this is a link
                    href = await card.get_attribute('href')
                    
                    if not href:
                        # Find link inside card
                        link = await card.query_selector('a[href*="/careers/"], a[href*="/openings/"]')
                        if link:
                            href = await link.get_attribute('href')
                    
                    if not href:
                        continue
                    
                    job_url = self.normalize_url(href)
                    if job_url in self.seen_urls:
                        continue
                    
                    # Get title
                    title = ""
                    for title_sel in self.TITLE_SELECTORS:
                        title_el = await card.query_selector(title_sel)
                        if title_el:
                            title = await title_el.text_content()
                            title = self.clean_text(title) if title else ""
                            if title and len(title) > 3:
                                break
                    
                    if not title:
                        title = await card.text_content()
                        title = self.clean_text(title) if title else ""
                        # Get first line only
                        if title and '\n' in title:
                            title = title.split('\n')[0].strip()
                    
                    if not title or len(title) < 3 or len(title) > 150:
                        continue
                    
                    if title in self.seen_titles:
                        continue
                    
                    self.seen_urls.add(job_url)
                    self.seen_titles.add(title)
                    
                    # Get location
                    location = ""
                    for loc_sel in self.LOCATION_SELECTORS:
                        loc_el = await card.query_selector(loc_sel)
                        if loc_el:
                            location = await loc_el.text_content()
                            location = self.clean_text(location) if location else ""
                            break
                    
                    job_id = self._extract_plaid_job_id(job_url)
                    
                    jobs.append(Job(
                        job_id=job_id,
                        job_title=title,
                        job_url=job_url,
                        company_name=self.company_name,
                        company_career_url=self.career_url,
                        location=location,
                    ))
                
                if jobs:
                    break
                    
            except Exception:
                continue
        
        return jobs

    async def _extract_jobs_from_links(self) -> List[Job]:
        """Fallback: Extract jobs from all career links."""
        jobs: List[Job] = []
        
        try:
            links = await self.page.query_selector_all('a[href*="/careers/"], a[href*="/openings/"]')
            
            for link in links:
                href = await link.get_attribute('href')
                if not href:
                    continue
                
                job_url = self.normalize_url(href)
                
                # Skip main careers page
                if job_url.rstrip('/').endswith('/careers'):
                    continue
                
                if job_url in self.seen_urls:
                    continue
                
                title = await link.text_content()
                title = self.clean_text(title) if title else ""
                
                # Skip generic link text
                if title.lower() in ['see role', 'apply', 'view', 'careers', 'openings']:
                    title = self._extract_title_from_url(job_url)
                
                if not title or len(title) < 3 or len(title) > 150:
                    continue
                
                if title in self.seen_titles:
                    continue
                
                self.seen_urls.add(job_url)
                self.seen_titles.add(title)
                
                job_id = self._extract_plaid_job_id(job_url)
                
                jobs.append(Job(
                    job_id=job_id,
                    job_title=title,
                    job_url=job_url,
                    company_name=self.company_name,
                    company_career_url=self.career_url,
                ))
                
        except Exception as e:
            print(f"    Link extraction error: {e}")
        
        return jobs

    def _extract_title_from_url(self, url: str) -> str:
        """Extract a readable title from URL path."""
        try:
            # Get last path segment
            path = urlparse(url).path
            segments = [s for s in path.split('/') if s and s not in ['careers', 'openings', 'engineering']]
            if segments:
                # Convert slug to title
                title = segments[-1].replace('-', ' ').replace('_', ' ').title()
                return title
        except Exception:
            pass
        return ""

    def _extract_plaid_job_id(self, url: str) -> str:
        """Extract or generate job ID for Plaid."""
        # Try to get from URL path
        match = re.search(r'/openings/([^/\?#]+)', url)
        if match:
            return f"PL_{match.group(1)[:30]}"
        
        match = re.search(r'/careers/([^/\?#]+)/([^/\?#]+)', url)
        if match:
            return f"PL_{match.group(2)[:30]}"
        
        return self.generate_job_id(url, "")
