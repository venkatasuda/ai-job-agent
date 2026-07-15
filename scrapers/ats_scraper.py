"""
ATS Scraper — scrapes company career pages directly via:
  - Greenhouse  (boards.greenhouse.io/<token>/jobs)
  - Lever       (jobs.lever.co/<company>)
  - Ashby       (jobs.ashbyhq.com/<company>)
  - Workday     (via JSON API)

This catches jobs that never appear on LinkedIn/Indeed.
"""

import logging
import requests
from typing import List, Dict, Any
from datetime import datetime, timezone
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    )
}


def _base_job(company: str, source: str) -> Dict[str, Any]:
    return {
        "id": "",
        "title": "",
        "company": company,
        "location": "",
        "description": "",
        "url": "",
        "apply_url": "",
        "salary_min": None,
        "salary_max": None,
        "job_type": "fulltime",
        "date_posted": "",
        "source": source,
        "is_remote": False,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "score": None,
        "cover_letter": None,
        "applied": False,
    }


class ATSScraper:
    def __init__(self, config: dict):
        self.cfg = config
        self.search_cfg = config.get("search", {})
        self.ats_cfg = config.get("sources", {}).get("ats_companies", {})
        self.keywords = [k.lower() for k in self.search_cfg.get("keywords", [])]

    def _keyword_match(self, title: str, description: str = "") -> bool:
        """Return True if any search keyword appears in title or description."""
        text = (title + " " + description).lower()
        return any(kw in text for kw in self.keywords)

    # ── Greenhouse ────────────────────────────────────────────────────────────

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=3, max=20))
    def _scrape_greenhouse(self, company: str, token: str) -> List[Dict]:
        url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning(f"Greenhouse [{company}] error: {e}")
            return []

        jobs = []
        for item in data.get("jobs", []):
            title = item.get("title", "")
            description = item.get("content", "")
            if not self._keyword_match(title, description):
                continue
            job = _base_job(company, "greenhouse")
            job["id"] = str(item.get("id", ""))
            job["title"] = title
            job["location"] = item.get("location", {}).get("name", "")
            job["description"] = description
            job["url"] = item.get("absolute_url", "")
            job["apply_url"] = item.get("absolute_url", "")
            job["date_posted"] = item.get("updated_at", "")[:10]
            jobs.append(job)

        logger.info(f"Greenhouse [{company}]: {len(jobs)} matching jobs")
        return jobs

    # ── Lever ─────────────────────────────────────────────────────────────────

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=3, max=20))
    def _scrape_lever(self, company: str, url_or_token: str) -> List[Dict]:
        # Accept either full URL or just token
        if url_or_token.startswith("http"):
            api_url = url_or_token.rstrip("/") + "?mode=json"
        else:
            api_url = f"https://api.lever.co/v0/postings/{url_or_token}?mode=json"

        try:
            resp = requests.get(api_url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning(f"Lever [{company}] error: {e}")
            return []

        jobs = []
        for item in data:
            title = item.get("text", "")
            description = item.get("descriptionPlain", "") or ""
            if not self._keyword_match(title, description):
                continue
            job = _base_job(company, "lever")
            job["id"] = item.get("id", "")
            job["title"] = title
            loc = item.get("categories", {}).get("location", "")
            job["location"] = loc
            job["is_remote"] = "remote" in loc.lower()
            job["description"] = description
            job["url"] = item.get("hostedUrl", "")
            job["apply_url"] = item.get("applyUrl", "")
            ts = item.get("createdAt", 0)
            job["date_posted"] = datetime.utcfromtimestamp(ts / 1000).strftime("%Y-%m-%d") if ts else ""
            jobs.append(job)

        logger.info(f"Lever [{company}]: {len(jobs)} matching jobs")
        return jobs

    # ── Ashby ─────────────────────────────────────────────────────────────────

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=3, max=20))
    def _scrape_ashby(self, company: str, url_or_token: str) -> List[Dict]:
        if url_or_token.startswith("http"):
            token = url_or_token.rstrip("/").split("/")[-1]
        else:
            token = url_or_token

        api_url = "https://api.ashbyhq.com/posting-api/job-board"
        try:
            resp = requests.post(
                api_url,
                json={"organizationHostedJobsPageName": token},
                headers={**HEADERS, "Content-Type": "application/json"},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning(f"Ashby [{company}] error: {e}")
            return []

        jobs = []
        for item in data.get("jobs", []):
            title = item.get("title", "")
            description = item.get("descriptionPlain", "") or ""
            if not self._keyword_match(title, description):
                continue
            job = _base_job(company, "ashby")
            job["id"] = item.get("id", "")
            job["title"] = title
            job["location"] = item.get("location", "")
            job["is_remote"] = item.get("isRemote", False)
            job["description"] = description
            job["url"] = item.get("jobUrl", "")
            job["apply_url"] = item.get("jobUrl", "")
            job["date_posted"] = item.get("publishedDate", "")[:10] if item.get("publishedDate") else ""
            jobs.append(job)

        logger.info(f"Ashby [{company}]: {len(jobs)} matching jobs")
        return jobs

    # ── Main ──────────────────────────────────────────────────────────────────

    def scrape(self) -> List[Dict[str, Any]]:
        if not self.ats_cfg.get("enabled", False):
            return []

        targets = self.ats_cfg.get("targets", [])
        all_jobs: Dict[str, Dict] = {}

        for target in targets:
            if len(target) != 3:
                continue
            company, ats_type, token_or_url = target

            if ats_type == "greenhouse":
                jobs = self._scrape_greenhouse(company, token_or_url)
            elif ats_type == "lever":
                jobs = self._scrape_lever(company, token_or_url)
            elif ats_type == "ashby":
                jobs = self._scrape_ashby(company, token_or_url)
            else:
                logger.warning(f"Unknown ATS type: {ats_type} for {company}")
                jobs = []

            for job in jobs:
                key = job["url"] or f"{company}_{job['title']}"
                if key not in all_jobs:
                    all_jobs[key] = job

        logger.info(f"ATS scraper total unique jobs: {len(all_jobs)}")
        return list(all_jobs.values())
