"""
New Grad Job Board Scraper
===========================
Scrapes job boards that are exclusive to or best for new grads / Masters graduates.
These jobs rarely appear on LinkedIn/Indeed.

Sources:
  1. Pitt CSC GitHub List  — github.com/SimplifyJobs/New-Grad-Positions (live JSON)
  2. Simplify.jobs         — curated new grad roles with Easy Apply
  3. Levels.fyi New Grad   — compensation-transparent new grad roles
  4. GitHub Job Lists      — multiple community-maintained new grad lists

All sources are public and don't require login.
"""

import logging
import requests
import re
from typing import List, Dict, Any
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
}

# Pitt CSC / SimplifyJobs maintains this as a live JSON file
PITTCSC_JSON_URL = "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/.github/scripts/listings.json"

# Simplify new grad search API
SIMPLIFY_URL = "https://simplify.jobs/api/jobs/search"


def _base_job(source: str) -> Dict[str, Any]:
    return {
        "title": "", "company": "", "location": "", "description": "",
        "url": "", "apply_url": "", "salary_min": None, "salary_max": None,
        "job_type": "fulltime", "date_posted": "", "source": source,
        "is_remote": False, "scraped_at": datetime.now(timezone.utc).isoformat(),
        "score": None, "cover_letter": None, "applied": False,
        "is_new_grad": True,
    }


class NewGradScraper:
    def __init__(self, config: dict):
        self.cfg = config
        self.search_cfg = config.get("search", {})
        self.newgrad_cfg = config.get("sources", {}).get("new_grad", {})
        self.keywords = [k.lower() for k in self.search_cfg.get("keywords", [])]

    def _keyword_match(self, title: str, description: str = "") -> bool:
        if not self.keywords:
            return True
        text = (title + " " + description).lower()
        return any(kw in text for kw in self.keywords)

    # ── Pitt CSC / SimplifyJobs GitHub List ──────────────────────────────────

    def _scrape_pittcsc(self) -> List[Dict]:
        """Fetch the live new-grad JSON from SimplifyJobs GitHub repo."""
        try:
            resp = requests.get(PITTCSC_JSON_URL, headers=HEADERS, timeout=20)
            resp.raise_for_status()
            listings = resp.json()
        except Exception as e:
            logger.warning(f"PittCSC scrape failed: {e}")
            return []

        jobs = []
        for item in listings:
            # Filter: active only
            if not item.get("active", True):
                continue

            title = item.get("title", "")
            company = item.get("company_name", "")
            locations = item.get("locations", [])
            location = ", ".join(locations) if locations else "United States"
            url = item.get("url", "")
            date_posted = item.get("date_posted", "")

            if not self._keyword_match(title):
                continue

            # Handle multiple URLs (some listings have multiple apply links)
            urls = item.get("urls", [url]) if not url else [url]
            for apply_url in urls[:1]:  # take first
                job = _base_job("pittcsc_newgrad")
                job["title"] = title
                job["company"] = company
                job["location"] = location
                job["is_remote"] = any("remote" in loc.lower() for loc in locations)
                job["url"] = apply_url or url
                job["apply_url"] = apply_url or url
                job["date_posted"] = str(date_posted)[:10] if date_posted else ""
                job["description"] = f"New graduate position at {company}. Role: {title}."
                jobs.append(job)

        logger.info(f"PittCSC/SimplifyJobs: {len(jobs)} matching new grad jobs")
        return jobs

    # ── Simplify.jobs API ─────────────────────────────────────────────────────

    def _scrape_simplify(self) -> List[Dict]:
        """Fetch from Simplify.jobs search API."""
        jobs = []
        for keyword in self.keywords[:5]:  # limit API calls
            try:
                resp = requests.get(
                    "https://simplify.jobs/api/search",
                    params={
                        "query": keyword,
                        "experience": "entry_level,new_grad",
                        "limit": 50,
                    },
                    headers=HEADERS,
                    timeout=15,
                )
                if resp.status_code != 200:
                    continue
                data = resp.json()
                results = data.get("jobs", data.get("results", []))
                for item in results:
                    title = item.get("title", "")
                    if not self._keyword_match(title):
                        continue
                    job = _base_job("simplify")
                    job["title"] = title
                    job["company"] = item.get("company", {}).get("name", "") if isinstance(item.get("company"), dict) else item.get("company", "")
                    job["location"] = item.get("location", "United States")
                    job["url"] = item.get("url", item.get("job_url", ""))
                    job["apply_url"] = item.get("apply_url", job["url"])
                    job["date_posted"] = str(item.get("date_posted") or "")[:10]
                    job["is_remote"] = item.get("remote", False)
                    job["description"] = item.get("description", "")[:1000]
                    if job["url"]:
                        jobs.append(job)
            except Exception as e:
                logger.warning(f"Simplify API [{keyword}]: {e}")

        # Dedupe by URL
        seen = set()
        unique = []
        for j in jobs:
            if j["url"] not in seen:
                seen.add(j["url"])
                unique.append(j)
        logger.info(f"Simplify.jobs: {len(unique)} matching new grad jobs")
        return unique

    # ── Community GitHub Lists ─────────────────────────────────────────────────

    def _scrape_github_lists(self) -> List[Dict]:
        """
        Scrape community-maintained GitHub new-grad job lists.
        These are markdown files with job tables — parse them with regex.
        """
        sources = [
            {
                "name": "xcandidates_newgrad",
                "url": "https://raw.githubusercontent.com/ReaVNaiL/New-Grad-2024/main/README.md",
            },
        ]
        jobs = []
        # Regex for markdown table rows: | Company | Role | Location | Link |
        row_pattern = re.compile(
            r'\|\s*\[?([^\|\]]+)\]?[^\|]*\|\s*([^\|]+)\|\s*([^\|]+)\|\s*\[?([^\|\]]*)\]?\(?([^)\s]*)\)?'
        )

        for source in sources:
            try:
                resp = requests.get(source["url"], headers=HEADERS, timeout=15)
                if resp.status_code != 200:
                    continue
                lines = resp.text.split("\n")
                for line in lines:
                    match = row_pattern.match(line.strip())
                    if not match:
                        continue
                    company = match.group(1).strip()
                    title = match.group(2).strip()
                    location = match.group(3).strip()
                    url = match.group(5).strip()
                    if not url.startswith("http") or not title:
                        continue
                    if not self._keyword_match(title):
                        continue
                    job = _base_job(source["name"])
                    job["company"] = company
                    job["title"] = title
                    job["location"] = location
                    job["url"] = url
                    job["apply_url"] = url
                    job["is_remote"] = "remote" in location.lower()
                    jobs.append(job)
            except Exception as e:
                logger.warning(f"GitHub list [{source['name']}]: {e}")

        logger.info(f"GitHub community lists: {len(jobs)} matching new grad jobs")
        return jobs

    # ── Main ──────────────────────────────────────────────────────────────────

    def scrape(self) -> List[Dict]:
        if not self.newgrad_cfg.get("enabled", True):
            return []

        all_jobs: Dict[str, Dict] = {}

        for job in self._scrape_pittcsc():
            key = job["url"] or f"{job['company']}_{job['title']}"
            if key and key not in all_jobs:
                all_jobs[key] = job

        for job in self._scrape_simplify():
            key = job["url"] or f"{job['company']}_{job['title']}"
            if key and key not in all_jobs:
                all_jobs[key] = job

        for job in self._scrape_github_lists():
            key = job["url"] or f"{job['company']}_{job['title']}"
            if key and key not in all_jobs:
                all_jobs[key] = job

        result = list(all_jobs.values())
        logger.info(f"New grad scraper total unique: {len(result)}")
        return result
