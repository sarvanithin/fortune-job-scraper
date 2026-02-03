"""
Eightfold AI career site scraper.
Handles sites like aexp.eightfold.ai, prudential.eightfold.ai, etc.

Eightfold uses a React-based SPA that loads jobs dynamically.
This scraper uses extensive selectors to find job listings in various layouts.

DEBUG VERSION - Enhanced logging to troubleshoot extraction issues.
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

    # Eightfold job link selectors - ordered by specificity
    # The key insight is to look for links that contain /position/ in href
    JOB_LINK_SELECTORS = [
        # Most specific: links with position in URL (Eightfold uses /position/ paths)
        'a[href*="/position/"]',
        'a[href*="positionId="]',
        'a[href*="/job/"]',
        # Links within specific containers
        '[class*="position"] a[href]',
        '[class*="Position"] a[href]',
        '[class*="job-card"] a[href]',
        '[class*="JobCard"] a[href]',
        '[class*="search-result"] a[href]',
        '[class*="SearchResult"] a[href]',
        # Role attributes
        '[role="listitem"] a[href*="position"]',
        '[role="option"] a[href]',
        # General patterns
        'main a[href*="position"]',
        'section a[href*="position"]',
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
                
                await self.page.goto(
                    self.career_url,
                    wait_until='networkidle',
                    timeout=PAGE_LOAD_TIMEOUT_MS * 2,
                )
                
                # Wait for React to fully render (Eightfold is slow)
                print(f"  [Eightfold] Waiting 10s for React to render...")
                await asyncio.sleep(10)
                
                # Try scrolling to load all content
                await self._scroll_to_load_all()

                # Extract jobs using multiple strategies
                print(f"  [Eightfold] Extracting jobs...")
                
                # Primary strategy: Find all position links
                jobs = await self._extract_position_links()
                
                if not jobs:
                    print(f"  [Eightfold] Primary extraction failed, trying deep search...")
                    jobs = await self._deep_search_for_jobs()
                
                all_jobs.extend(jobs)
                
                # Try scrolling and loading more
                for page_num in range(2, MAX_PAGES_PER_COMPANY + 1):
                    more_loaded = await self._load_more_jobs()
                    if not more_loaded:
                        break
                    
                    await asyncio.sleep(2)
                    new_jobs = await self._extract_position_links()
                    
                    new_count = 0
                    for job in new_jobs:
                        if job.job_url not in self.seen_urls:
                            self.seen_urls.add(job.job_url)
                            all_jobs.append(job)
                            new_count += 1
                    
                    if new_count == 0:
                        break
                    print(f"  [Eightfold] Page {page_num}: Found {new_count} more jobs")

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
        """Scroll to trigger lazy loading."""
        try:
            print(f"  [Eightfold] Scrolling page...")
            
            # Multiple scroll iterations
            for i in range(10):
                await self.page.evaluate('window.scrollBy(0, 500)')
                await asyncio.sleep(0.5)
            
            # Scroll back to top
            await self.page.evaluate('window.scrollTo(0, 0)')
            await asyncio.sleep(1)
            
        except Exception:
            pass

    async def _extract_position_links(self) -> List[Job]:
        """Extract jobs by finding all links that point to job positions."""
        jobs: List[Job] = []
        
        for selector in self.JOB_LINK_SELECTORS:
            try:
                elements = await self.page.query_selector_all(selector)
                
                if elements:
                    print(f"    Trying selector: {selector} -> {len(elements)} elements")
                
                for element in elements:
                    job = await self._parse_link_element(element)
                    if job and job.job_url not in self.seen_urls:
                        self.seen_urls.add(job.job_url)
                        self.seen_titles.add(job.job_title)
                        jobs.append(job)
                
                # If we found jobs with this selector, log and continue trying other selectors
                # (don't break - collect from all selectors to get more)
                
            except Exception as e:
                continue
        
        # Deduplicate by URL
        unique_jobs = []
        seen = set()
        for job in jobs:
            if job.job_url not in seen:
                seen.add(job.job_url)
                unique_jobs.append(job)
        
        print(f"    Total unique jobs extracted: {len(unique_jobs)}")
        return unique_jobs

    async def _parse_link_element(self, element) -> Optional[Job]:
        """Parse a link element to extract job info."""
        try:
            href = await element.get_attribute('href')
            if not href:
                return None
            
            # Normalize URL
            job_url = self.normalize_url(href)
            
            # Must be a position/job URL
            if not any(x in job_url.lower() for x in ['/position/', 'positionid=', '/job/']):
                return None
            
            # Skip non-job links
            skip_patterns = ['/login', '/apply/', '/saved', '/share', '/filter', 'javascript:']
            if any(x in job_url.lower() for x in skip_patterns):
                return None
            
            # Get text content as title
            text = await element.text_content()
            title = self.clean_text(text) if text else ""
            
            # If title is too long, it might include child element text
            if len(title) > 150:
                # Try to get just the first line
                title = title.split('\n')[0].strip()[:150]
            
            # Title must be reasonable
            if not title or len(title) < 3:
                # Try to extract from URL
                title = self._title_from_url(job_url)
            
            if not title or len(title) < 3:
                return None
            
            # Try to find location in parent or sibling
            location = await self._find_location_near(element)
            
            # Generate job ID
            job_id = self._extract_job_id(job_url) or self.generate_job_id(job_url, title)
            
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

    async def _find_location_near(self, element) -> str:
        """Try to find location text near the element."""
        try:
            # Look in parent container
            parent = await element.evaluate_handle('el => el.parentElement')
            if parent:
                location_selectors = [
                    '[class*="location"]',
                    '[class*="Location"]',
                    'span:has-text("United States")',
                    'span:has-text("New York")',
                    'span:has-text("Remote")',
                ]
                for sel in location_selectors:
                    try:
                        loc_el = await parent.query_selector(sel)
                        if loc_el:
                            loc_text = await loc_el.text_content()
                            return self.clean_text(loc_text) if loc_text else ""
                    except Exception:
                        continue
        except Exception:
            pass
        return ""

    def _title_from_url(self, url: str) -> str:
        """Extract a readable title from URL path."""
        try:
            match = re.search(r'/position/([^/?]+)', url)
            if match:
                slug = match.group(1)
                # Convert slug to title (replace dashes/underscores with spaces)
                title = slug.replace('-', ' ').replace('_', ' ').title()
                return title[:100]
        except Exception:
            pass
        return ""

    def _extract_job_id(self, url: str) -> Optional[str]:
        """Extract job ID from Eightfold URL."""
        patterns = [
            r'/position/([A-Za-z0-9_-]+)',
            r'positionId=([A-Za-z0-9_-]+)',
            r'/job/([A-Za-z0-9_-]+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return f"EF_{match.group(1)[:20]}"
        return None

    async def _deep_search_for_jobs(self) -> List[Job]:
        """Deep search: enumerate all links and filter for job-like ones."""
        jobs: List[Job] = []
        
        try:
            # Get ALL links on page
            all_links = await self.page.query_selector_all('a[href]')
            print(f"    Deep search: Found {len(all_links)} total links")
            
            job_link_count = 0
            for link in all_links:
                href = await link.get_attribute('href')
                if not href:
                    continue
                
                # Only process job-like URLs
                href_lower = href.lower()
                if not any(x in href_lower for x in ['/position/', 'positionid=', '/job/', '/careers/']):
                    continue
                if any(x in href_lower for x in ['/login', '/saved', 'javascript:', '#']):
                    continue
                
                job_link_count += 1
                
                # Parse the link
                job = await self._parse_link_element(link)
                if job and job.job_url not in self.seen_urls:
                    self.seen_urls.add(job.job_url)
                    jobs.append(job)
            
            print(f"    Deep search: Found {job_link_count} job-like links, extracted {len(jobs)} jobs")
            
        except Exception as e:
            print(f"    Deep search error: {e}")
        
        return jobs

    async def _load_more_jobs(self) -> bool:
        """Try to load more jobs via buttons or scrolling."""
        
        # Try load more buttons
        load_more_selectors = [
            'button:has-text("Load more")',
            'button:has-text("Show more")',
            'button:has-text("View more")',
            '[data-test-id="load-more"]',
            '[class*="load-more"]',
        ]
        
        for selector in load_more_selectors:
            try:
                button = await self.page.query_selector(selector)
                if button and await button.is_visible():
                    disabled = await button.get_attribute('disabled')
                    if not disabled:
                        await button.click()
                        await asyncio.sleep(3)
                        return True
            except Exception:
                continue
        
        # Try pagination
        pagination_selectors = [
            'button[aria-label*="next" i]',
            'a[aria-label*="next" i]',
            '[class*="pagination"] button:last-child:not([disabled])',
        ]
        
        for selector in pagination_selectors:
            try:
                button = await self.page.query_selector(selector)
                if button and await button.is_visible():
                    await button.click()
                    await self.page.wait_for_load_state('networkidle', timeout=10000)
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
