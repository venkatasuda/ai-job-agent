"""
Notion / Airtable Sync
========================
Syncs your job applications to Notion database or Airtable base.

This lets you:
  - View your job pipeline in a beautiful Kanban board in Notion
  - Share your job search progress with mentors/family
  - Add custom notes, tags, and tracking
  - View on mobile easily

Notion Setup:
  1. Create a Notion integration at https://www.notion.so/my-integrations
  2. Create a database with these properties:
     Title, Company, Status, Score, URL, Date Applied, Stage, Notes
  3. Share the database with your integration
  4. Set notion_token + database_id in config

Airtable Setup:
  1. Create account at https://airtable.com
  2. Create a base with "Job Applications" table
  3. Get Personal Access Token from https://airtable.com/create/tokens
  4. Get base ID from URL (starts with 'app...')
"""

import json
import logging
import os
import requests
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

NOTION_API = "https://api.notion.com/v1"
AIRTABLE_API = "https://api.airtable.com/v0"

# Stage → Notion status mapping
STAGE_TO_NOTION = {
    "not_applied": "Not Applied",
    "applied": "Applied",
    "phone_screen": "Phone Screen",
    "technical": "Technical Round",
    "system_design": "System Design",
    "onsite": "Onsite",
    "offer": "Offer Received",
    "negotiating": "Negotiating",
    "accepted": "Accepted",
    "rejected": "Rejected",
    "withdrawn": "Withdrawn",
}


class NotionSync:
    def __init__(self, config: dict):
        self.cfg = config.get("integrations", {}).get("notion", {})
        self.enabled = self.cfg.get("enabled", False)
        self.token = self.cfg.get("token") or os.environ.get("NOTION_TOKEN", "")
        self.database_id = self.cfg.get("database_id", "")
        self._page_map: Dict[str, str] = {}  # job_id → notion_page_id
        self._map_path_str = "notion_page_map.json"
        self._load_map()

    def _load_map(self):
        import pathlib
        p = pathlib.Path(self._map_path_str)
        if p.exists():
            try:
                self._page_map = json.loads(p.read_text())
            except Exception:
                pass

    def _save_map(self):
        import pathlib
        pathlib.Path(self._map_path_str).write_text(json.dumps(self._page_map))

    @property
    def _headers(self) -> Dict:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28",
        }

    def _job_to_notion_props(self, job: Dict) -> Dict:
        """Convert job dict to Notion page properties."""
        stage = STAGE_TO_NOTION.get(job.get("interview_stage", "applied"), "Applied")
        return {
            "Name": {"title": [{"text": {"content": job.get("title", "Unknown")[:200]}}]},
            "Company": {"rich_text": [{"text": {"content": job.get("company", "")[:200]}}]},
            "Status": {"select": {"name": stage}},
            "Score": {"number": job.get("score") or 0},
            "URL": {"url": job.get("job_url") or job.get("url") or None},
            "Location": {"rich_text": [{"text": {"content": job.get("location", "")[:200]}}]},
            "Source": {"select": {"name": job.get("source", "unknown")[:100]}},
            "Remote": {"checkbox": bool(job.get("is_remote"))},
            "Date Applied": {"date": {"start": datetime.utcnow().date().isoformat()}
                            if job.get("interview_stage") != "not_applied" else None},
            "ATS Score": {"number": job.get("ats_score") or 0},
        }

    def upsert_job(self, job: Dict) -> Optional[str]:
        """Create or update a job in Notion. Returns page ID."""
        if not self.enabled or not self.token or not self.database_id:
            return None
        job_id = str(job.get("id", ""))
        try:
            props = self._job_to_notion_props(job)
            # Remove None values from date
            if props.get("Date Applied", {}).get("date") is None:
                del props["Date Applied"]

            if job_id in self._page_map:
                # Update existing page
                resp = requests.patch(
                    f"{NOTION_API}/pages/{self._page_map[job_id]}",
                    headers=self._headers,
                    json={"properties": props},
                    timeout=10,
                )
                if resp.status_code == 200:
                    return self._page_map[job_id]
            else:
                # Create new page
                resp = requests.post(
                    f"{NOTION_API}/pages",
                    headers=self._headers,
                    json={"parent": {"database_id": self.database_id}, "properties": props},
                    timeout=10,
                )
                if resp.status_code == 200:
                    page_id = resp.json().get("id")
                    self._page_map[job_id] = page_id
                    self._save_map()
                    return page_id
        except Exception as e:
            logger.error(f"Notion sync error for {job.get('title')}: {e}")
        return None

    def sync_batch(self, jobs: List[Dict], min_score: int = 70) -> Dict:
        """Sync a batch of jobs to Notion."""
        synced, failed = 0, 0
        high_score = [j for j in jobs if (j.get("score") or 0) >= min_score]
        for job in high_score:
            if self.upsert_job(job):
                synced += 1
            else:
                failed += 1
        return {"synced": synced, "failed": failed, "total": len(high_score)}

    @staticmethod
    def get_setup_guide() -> str:
        return """
Notion Sync Setup:
==================
1. Go to https://www.notion.so/my-integrations → "New integration"
2. Name: "Job Agent" → Submit
3. Copy the "Internal Integration Token"
4. Create a new Notion database (full page, not inline)
5. Click "..." menu → "Add connections" → add your integration
6. Copy the database ID from the URL:
   notion.so/YOUR_WORKSPACE/<DATABASE_ID>?v=...
7. Add to config.yaml:
   integrations:
     notion:
       enabled: true
       token: "secret_..."
       database_id: "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
"""


class AirtableSync:
    def __init__(self, config: dict):
        self.cfg = config.get("integrations", {}).get("airtable", {})
        self.enabled = self.cfg.get("enabled", False)
        self.token = self.cfg.get("token") or os.environ.get("AIRTABLE_TOKEN", "")
        self.base_id = self.cfg.get("base_id", "")
        self.table_name = self.cfg.get("table_name", "Job Applications")
        self._record_map: Dict[str, str] = {}
        self._map_path_str = "airtable_record_map.json"
        self._load_map()

    def _load_map(self):
        import pathlib
        p = pathlib.Path(self._map_path_str)
        if p.exists():
            try:
                self._record_map = json.loads(p.read_text())
            except Exception:
                pass

    def _save_map(self):
        import pathlib
        pathlib.Path(self._map_path_str).write_text(json.dumps(self._record_map))

    @property
    def _headers(self) -> Dict:
        return {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}

    def _job_to_fields(self, job: Dict) -> Dict:
        return {
            "Job Title": job.get("title", ""),
            "Company": job.get("company", ""),
            "Status": STAGE_TO_NOTION.get(job.get("interview_stage", "applied"), "Applied"),
            "Match Score": job.get("score") or 0,
            "URL": job.get("job_url") or job.get("url") or "",
            "Location": job.get("location") or "",
            "Remote": bool(job.get("is_remote")),
            "Source": job.get("source", ""),
            "ATS Score": job.get("ats_score") or 0,
        }

    def upsert_job(self, job: Dict) -> Optional[str]:
        if not self.enabled or not self.token or not self.base_id:
            return None
        job_id = str(job.get("id", ""))
        url = f"{AIRTABLE_API}/{self.base_id}/{self.table_name}"
        try:
            fields = self._job_to_fields(job)
            if job_id in self._record_map:
                resp = requests.patch(
                    f"{url}/{self._record_map[job_id]}",
                    headers=self._headers, json={"fields": fields}, timeout=10,
                )
            else:
                resp = requests.post(
                    url, headers=self._headers, json={"fields": fields}, timeout=10,
                )
                if resp.status_code in (200, 201):
                    record_id = resp.json().get("id")
                    self._record_map[job_id] = record_id
                    self._save_map()
                    return record_id
            return self._record_map.get(job_id)
        except Exception as e:
            logger.error(f"Airtable sync error: {e}")
        return None

    def sync_batch(self, jobs: List[Dict], min_score: int = 70) -> Dict:
        synced, failed = 0, 0
        for job in jobs:
            if (job.get("score") or 0) >= min_score:
                if self.upsert_job(job):
                    synced += 1
                else:
                    failed += 1
        return {"synced": synced, "failed": failed}
