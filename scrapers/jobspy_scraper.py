"""
JobSpy Scraper — wraps speedyapply/JobSpy to pull from
LinkedIn, Indeed, Glassdoor, Google Jobs, ZipRecruiter simultaneously.
"""

import logging
from typing import List, Dict, Any
from datetime import datetime
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


class JobSpyScraper:
    def __init__(self, config: dict):
        self.cfg = config
        self.search_cfg = config.get("search", {})
        self.source_cfg = config.get("sources", {}).get("jobspy", {})

    def _normalize_job(self, job) -> Dict[str, Any]:
        """Convert a JobSpy row to our standard dict."""
        return {
            "id": str(job.get("id", "")),
            "title": str(job.get("title", "")),
            "company": str(job.get("company", "")),
            "location": str(job.get("location", "")),
            "description": str(job.get("description", "") or ""),
            "url": str(job.get("job_url", "")),
            "apply_url": str(job.get("job_url_direct", "") or job.get("job_url", "")),
            "salary_min": job.get("min_amount"),
            "salary_max": job.get("max_amount"),
            "job_type": str(job.get("job_type", "")),
            "date_posted": str(job.get("date_posted", "")),
            "source": str(job.get("site", "jobspy")),
            "is_remote": bool(job.get("is_remote", False)),
            "scraped_at": datetime.utcnow().isoformat(),
            "score": None,
            "cover_letter": None,
            "applied": False,
        }

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=4, max=30))
    def _scrape_keyword_location(self, keyword: str, location: str) -> List[Dict]:
        """Scrape one keyword+location combo across all configured sites."""
        try:
            from jobspy import scrape_jobs

            sites = self.source_cfg.get("sites", ["linkedin", "indeed", "glassdoor"])
            results_wanted = self.source_cfg.get("results_per_site", 30)

            df = scrape_jobs(
                site_name=sites,
                search_term=keyword,
                location=location,
                results_wanted=results_wanted,
                hours_old=2,           # Only jobs posted in last 2 hours per hourly run
                country_indeed="USA",
                linkedin_fetch_description=True,
            )

            if df is None or df.empty:
                return []

            jobs = []
            for _, row in df.iterrows():
                job = self._normalize_job(row.to_dict())
                if self._passes_filters(job):
                    jobs.append(job)

            logger.info(f"JobSpy [{keyword} / {location}]: {len(jobs)} jobs after filtering")
            return jobs

        except Exception as e:
            logger.error(f"JobSpy scrape error [{keyword}/{location}]: {e}")
            return []

    def _passes_filters(self, job: Dict) -> bool:
        """Apply user-configured filters to a job."""
        cfg = self.search_cfg

        # Excluded companies
        excluded_companies = [c.lower() for c in cfg.get("excluded_companies", [])]
        if job["company"].lower() in excluded_companies:
            return False

        # Excluded keywords in title or description
        excluded_kw = [k.lower() for k in cfg.get("excluded_keywords", [])]
        combined_text = (job["title"] + " " + job["description"]).lower()
        if any(kw in combined_text for kw in excluded_kw):
            return False

        # Minimum salary filter
        min_salary = cfg.get("min_salary", 0)
        if min_salary and job["salary_min"] is not None:
            if job["salary_min"] < min_salary:
                return False

        return True

    def scrape(self) -> List[Dict[str, Any]]:
        """Run all keyword × location combinations and return deduplicated jobs."""
        keywords = self.search_cfg.get("keywords", [])
        locations = self.search_cfg.get("locations", ["United States"])

        all_jobs: Dict[str, Dict] = {}  # url → job (dedupe by URL)

        for keyword in keywords:
            for location in locations:
                jobs = self._scrape_keyword_location(keyword, location)
                for job in jobs:
                    key = job["url"] or f"{job['company']}_{job['title']}"
                    if key and key not in all_jobs:
                        all_jobs[key] = job

        result = list(all_jobs.values())
        logger.info(f"JobSpy total unique jobs scraped: {len(result)}")
        return result
