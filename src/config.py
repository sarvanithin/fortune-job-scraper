"""
Configuration settings for the Fortune Job Scraper.
"""
import os
from typing import List

# Keywords to filter jobs - case insensitive matching
KEYWORDS: List[str] = [
    "data",
    "analyst",
    "analytics",
    "machine learning",
    "ml",
    "data science",
    "data scientist",
    "data engineer",
    "data analyst",
    "business intelligence",
    "bi",
    "ai",
    "artificial intelligence",
]

# Scraping settings
SCRAPE_DELAY_SECONDS: float = 2.0  # Delay between page loads (be respectful)
PAGE_LOAD_TIMEOUT_MS: int = 30000  # 30 seconds for page to load
MAX_PAGES_PER_COMPANY: int = 50  # Maximum pages to scrape per company
MAX_RETRIES: int = 3  # Retries on failure

# Batch settings (for large-scale scraping)
COMPANIES_PER_BATCH: int = 10  # Process companies in batches
BATCH_DELAY_SECONDS: float = 5.0  # Delay between batches

# Google Sheets settings
COMPANIES_SHEET_ID: str = os.getenv("COMPANIES_SHEET_ID", "")
JOBS_SHEET_ID: str = os.getenv("JOBS_SHEET_ID", "")

# Sheet names (tabs within the spreadsheet)
COMPANIES_SHEET_NAME: str = "Sheet1"
JOBS_SHEET_NAME: str = "Sheet1"

# Job status values
STATUS_ACTIVE: str = "active"
STATUS_REMOVED: str = "removed"
STATUS_ERROR: str = "error"

# Platform detection patterns
WORKDAY_PATTERNS: List[str] = [
    "myworkdayjobs.com",
    "wd1.myworkdayjobs",
    "wd3.myworkdayjobs",
    "wd5.myworkdayjobs",
]

EIGHTFOLD_PATTERNS: List[str] = [
    "eightfold.ai",
]

GREENHOUSE_PATTERNS: List[str] = [
    "greenhouse.io",
    "boards.greenhouse.io",
]

LEVER_PATTERNS: List[str] = [
    "lever.co",
    "jobs.lever.co",
]
