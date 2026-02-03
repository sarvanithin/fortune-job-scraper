"""
Google Sheets API client for reading company URLs and writing job listings.
"""
import json
import os
from datetime import datetime
from typing import List, Dict, Any, Optional

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from config import (
    COMPANIES_SHEET_ID,
    JOBS_SHEET_ID,
    COMPANIES_SHEET_NAME,
    JOBS_SHEET_NAME,
)


class SheetsClient:
    """Client for interacting with Google Sheets API."""

    SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

    def __init__(self, credentials_path: Optional[str] = None):
        """
        Initialize the Sheets client.

        Args:
            credentials_path: Path to credentials.json file.
                             If None, uses GOOGLE_CREDENTIALS env var.
        """
        self.credentials = self._load_credentials(credentials_path)
        self.service = build("sheets", "v4", credentials=self.credentials)
        self.sheets = self.service.spreadsheets()

    def _load_credentials(self, credentials_path: Optional[str] = None):
        """Load Google credentials from file or environment variable."""
        if credentials_path and os.path.exists(credentials_path):
            return service_account.Credentials.from_service_account_file(
                credentials_path, scopes=self.SCOPES
            )

        # Try environment variable (for GitHub Actions)
        creds_json = os.getenv("GOOGLE_CREDENTIALS")
        if creds_json:
            creds_info = json.loads(creds_json)
            return service_account.Credentials.from_service_account_info(
                creds_info, scopes=self.SCOPES
            )

        raise ValueError(
            "No credentials found. Provide credentials_path or set GOOGLE_CREDENTIALS env var."
        )

    def get_companies(self, sheet_id: Optional[str] = None) -> List[Dict[str, str]]:
        """
        Fetch company URLs from the companies sheet.

        Returns:
            List of dicts with keys: company_name, career_url, platform_type, status
        """
        sheet_id = sheet_id or COMPANIES_SHEET_ID
        if not sheet_id:
            raise ValueError("COMPANIES_SHEET_ID not configured")

        try:
            result = self.sheets.values().get(
                spreadsheetId=sheet_id,
                range=f"{COMPANIES_SHEET_NAME}!A:E",
            ).execute()

            values = result.get("values", [])
            if not values:
                return []

            # Skip header row
            companies = []
            for row in values[1:]:
                if len(row) >= 2:
                    companies.append({
                        "company_name": row[0] if len(row) > 0 else "",
                        "career_url": row[1] if len(row) > 1 else "",
                        "platform_type": row[2] if len(row) > 2 else "",
                        "last_scraped": row[3] if len(row) > 3 else "",
                        "status": row[4] if len(row) > 4 else "active",
                    })

            return companies

        except HttpError as e:
            print(f"Error fetching companies: {e}")
            raise

    def get_existing_job_ids(self, sheet_id: Optional[str] = None) -> set:
        """
        Fetch all existing job IDs from the jobs sheet for deduplication.

        Returns:
            Set of job IDs already in the sheet.
        """
        sheet_id = sheet_id or JOBS_SHEET_ID
        if not sheet_id:
            raise ValueError("JOBS_SHEET_ID not configured")

        try:
            result = self.sheets.values().get(
                spreadsheetId=sheet_id,
                range=f"{JOBS_SHEET_NAME}!A:A",
            ).execute()

            values = result.get("values", [])
            # Skip header, extract job IDs
            return {row[0] for row in values[1:] if row}

        except HttpError as e:
            print(f"Error fetching existing jobs: {e}")
            raise

    def append_jobs(
        self, jobs: List[Dict[str, Any]], sheet_id: Optional[str] = None
    ) -> int:
        """
        Append new jobs to the jobs sheet.

        Args:
            jobs: List of job dicts with keys matching sheet columns.

        Returns:
            Number of jobs appended.
        """
        sheet_id = sheet_id or JOBS_SHEET_ID
        if not sheet_id:
            raise ValueError("JOBS_SHEET_ID not configured")

        if not jobs:
            return 0

        # Convert jobs to rows
        rows = []
        now = datetime.utcnow().isoformat()

        for job in jobs:
            rows.append([
                job.get("job_id", ""),
                job.get("job_title", ""),
                job.get("company_name", ""),
                job.get("job_url", ""),
                job.get("company_career_url", ""),
                job.get("location", ""),
                now,  # date_added
                now,  # last_seen
                ", ".join(job.get("keywords_matched", [])),
                "active",
            ])

        try:
            result = self.sheets.values().append(
                spreadsheetId=sheet_id,
                range=f"{JOBS_SHEET_NAME}!A:J",
                valueInputOption="USER_ENTERED",
                insertDataOption="INSERT_ROWS",
                body={"values": rows},
            ).execute()

            updates = result.get("updates", {})
            return updates.get("updatedRows", 0)

        except HttpError as e:
            print(f"Error appending jobs: {e}")
            raise

    def update_company_status(
        self,
        company_name: str,
        status: str,
        sheet_id: Optional[str] = None,
    ):
        """Update the status and last_scraped time for a company."""
        sheet_id = sheet_id or COMPANIES_SHEET_ID
        if not sheet_id:
            return

        try:
            # First, find the row for this company
            result = self.sheets.values().get(
                spreadsheetId=sheet_id,
                range=f"{COMPANIES_SHEET_NAME}!A:A",
            ).execute()

            values = result.get("values", [])
            row_index = None
            for i, row in enumerate(values):
                if row and row[0] == company_name:
                    row_index = i + 1  # 1-indexed
                    break

            if row_index:
                now = datetime.utcnow().isoformat()
                self.sheets.values().update(
                    spreadsheetId=sheet_id,
                    range=f"{COMPANIES_SHEET_NAME}!D{row_index}:E{row_index}",
                    valueInputOption="USER_ENTERED",
                    body={"values": [[now, status]]},
                ).execute()

        except HttpError as e:
            print(f"Error updating company status: {e}")

    def update_job_last_seen(
        self, job_ids: List[str], sheet_id: Optional[str] = None
    ):
        """Update the last_seen timestamp for existing jobs."""
        sheet_id = sheet_id or JOBS_SHEET_ID
        if not sheet_id or not job_ids:
            return

        try:
            # Get all job IDs with their row numbers
            result = self.sheets.values().get(
                spreadsheetId=sheet_id,
                range=f"{JOBS_SHEET_NAME}!A:A",
            ).execute()

            values = result.get("values", [])
            now = datetime.utcnow().isoformat()

            # Build batch update
            requests = []
            for i, row in enumerate(values[1:], start=2):  # Skip header, 1-indexed
                if row and row[0] in job_ids:
                    requests.append({
                        "range": f"{JOBS_SHEET_NAME}!H{i}",
                        "values": [[now]],
                    })

            if requests:
                self.sheets.values().batchUpdate(
                    spreadsheetId=sheet_id,
                    body={
                        "valueInputOption": "USER_ENTERED",
                        "data": requests,
                    },
                ).execute()

        except HttpError as e:
            print(f"Error updating job last_seen: {e}")
