"""
Job Board Auto-Subscriber
==========================
Automates job alert subscriptions across multiple platforms
so new jobs flow into your inbox without manual searching.

Supported:
  - LinkedIn Job Alerts (via browser automation)
  - Indeed Email Alerts (via indeed.com RSS/email API)
  - Glassdoor Alerts
  - Remote.co / We Work Remotely RSS feeds
  - GitHub Jobs / HN Who's Hiring RSS parsers
  - Custom company career page RSS

This module also acts as an RSS aggregator — most job boards
have undocumented RSS feeds that work without authentication.
"""

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import quote

logger = logging.getLogger(__name__)


# Free RSS feeds that require no login
RSS_FEEDS = {
    "remoteok": "https://remoteok.com/remote-dev-jobs.rss",
    "weworkremotely_programming": "https://weworkremotely.com/categories/remote-programming-jobs.rss",
    "weworkremotely_devops": "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
    "weworkremotely_data": "https://weworkremotely.com/categories/remote-data-science-ai-jobs.rss",
    "remoteco_software": "https://remote.co/job-category/software-development/feed/",
    "stackoverflow": "https://stackoverflow.com/jobs/feed",
    "github_jobs": "https://jobs.github.com/positions.json",
}

INDEED_RSS_TEMPLATE = (
    "https://www.indeed.com/rss?q={query}&l={location}&sort=date&limit=25"
)

HN_JOBS_URL = "https://news.ycombinator.com/jobs"


class JobBoardSubscriber:
    def __init__(self, config: dict):
        self.cfg = config
        self.search_cfg = config.get("search", {})
        self.keywords = self.search_cfg.get("keywords", ["Software Engineer"])
        self.locations = self.search_cfg.get("locations", ["United States"])
        self._feed_state_path = Path("feed_state.json")
        self._feed_state = self._load_state()

    def _load_state(self) -> dict:
        if self._feed_state_path.exists():
            try:
                return json.loads(self._feed_state_path.read_text())
            except Exception:
                pass
        return {"last_fetched": {}, "seen_ids": []}

    def _save_state(self):
        self._feed_state["seen_ids"] = self._feed_state.get("seen_ids", [])[-5000:]
        self._feed_state_path.write_text(json.dumps(self._feed_state, indent=2))

    def _parse_rss(self, xml: str, source: str) -> List[Dict]:
        """Parse RSS XML into job dicts."""
        jobs = []
        try:
            # Simple regex-based RSS parser (no external dependency)
            items = re.findall(r"<item>(.*?)</item>", xml, re.DOTALL)
            for item in items:
                def extract(tag, text=item):
                    m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", text, re.DOTALL)
                    if m:
                        v = m.group(1).strip()
                        v = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", v, flags=re.DOTALL)
                        return re.sub(r"<[^>]+>", "", v).strip()
                    return ""

                title = extract("title")
                link = extract("link") or extract("guid")
                description = extract("description")[:1000]
                pub_date = extract("pubDate") or extract("published")

                if not title or title in self._feed_state.get("seen_ids", []):
                    continue

                job = {
                    "title": title,
                    "company": extract("author") or extract("company") or source,
                    "location": extract("location") or "Remote/Unknown",
                    "job_url": link,
                    "description": description,
                    "source": source,
                    "date_posted": pub_date or datetime.now(timezone.utc).isoformat(),
                    "is_remote": bool(re.search(r"(?i)remote", title + description)),
                }
                jobs.append(job)
                self._feed_state.setdefault("seen_ids", []).append(title)
        except Exception as e:
            logger.error(f"RSS parse error ({source}): {e}")
        return jobs

    def fetch_rss_feeds(self) -> List[Dict]:
        """Fetch all configured RSS job feeds."""
        try:
            import requests
        except ImportError:
            logger.error("pip install requests")
            return []

        all_jobs = []
        headers = {"User-Agent": "Mozilla/5.0 (compatible; JobAgent/1.0)"}

        for name, url in RSS_FEEDS.items():
            try:
                last = self._feed_state.get("last_fetched", {}).get(name, "")
                resp = requests.get(url, headers=headers, timeout=12)
                if resp.status_code == 200:
                    jobs = self._parse_rss(resp.text, name)
                    all_jobs.extend(jobs)
                    self._feed_state.setdefault("last_fetched", {})[name] = (
                        datetime.now(timezone.utc).isoformat()
                    )
                    logger.info(f"RSS {name}: {len(jobs)} new jobs")
            except Exception as e:
                logger.warning(f"RSS feed {name} failed: {e}")

        # Indeed RSS per keyword
        for keyword in self.keywords[:3]:
            for location in self.locations[:2]:
                url = INDEED_RSS_TEMPLATE.format(
                    query=quote(keyword), location=quote(location)
                )
                try:
                    resp = requests.get(url, headers=headers, timeout=12)
                    if resp.status_code == 200:
                        jobs = self._parse_rss(resp.text, "indeed_rss")
                        all_jobs.extend(jobs)
                except Exception as e:
                    logger.warning(f"Indeed RSS failed for {keyword}: {e}")

        self._save_state()
        logger.info(f"Total RSS jobs fetched: {len(all_jobs)}")
        return all_jobs

    def fetch_hn_who_is_hiring(self) -> List[Dict]:
        """Scrape Hacker News 'Who is Hiring?' monthly thread."""
        try:
            import requests
            # Get latest "Ask HN: Who is hiring?" post
            resp = requests.get(
                "https://hn.algolia.com/api/v1/search",
                params={
                    "query": "Ask HN: Who is hiring?",
                    "tags": "ask_hn",
                    "hitsPerPage": 3,
                },
                timeout=10,
            )
            hits = resp.json().get("hits", [])
            if not hits:
                return []

            latest = hits[0]
            story_id = latest.get("objectID")
            comments_resp = requests.get(
                f"https://hn.algolia.com/api/v1/items/{story_id}",
                timeout=10,
            )
            story = comments_resp.json()
            jobs = []
            for comment in (story.get("children") or [])[:200]:
                text = comment.get("text") or ""
                if not text or len(text) < 100:
                    continue
                # Remove HTML
                clean = re.sub(r"<[^>]+>", " ", text)
                # Extract company name (often first line or bold)
                lines = [l.strip() for l in clean.split("\n") if l.strip()]
                title = "Software Engineer"
                company = lines[0][:60] if lines else "HN Company"
                job = {
                    "title": title,
                    "company": company,
                    "location": "See posting",
                    "job_url": f"https://news.ycombinator.com/item?id={comment.get('id')}",
                    "description": clean[:1500],
                    "source": "hn_who_is_hiring",
                    "is_remote": bool(re.search(r"(?i)remote", clean)),
                    "date_posted": datetime.now(timezone.utc).isoformat(),
                }
                jobs.append(job)
            logger.info(f"HN Who is Hiring: {len(jobs)} postings")
            return jobs
        except Exception as e:
            logger.error(f"HN scrape error: {e}")
            return []

    def get_indeed_alert_setup_url(self, keyword: str, location: str) -> str:
        """Generate Indeed job alert signup URL."""
        return (
            f"https://www.indeed.com/prefs/alerts?q={quote(keyword)}"
            f"&l={quote(location)}&sort=date"
        )

    def get_linkedin_alert_url(self, keyword: str) -> str:
        """Generate LinkedIn job alert URL."""
        return (
            f"https://www.linkedin.com/jobs/search/?keywords={quote(keyword)}"
            f"&f_TPR=r86400&sortBy=DD"  # Past 24 hours, sorted by date
        )

    def scrape(self) -> List[Dict]:
        """Main entry point — fetch from all free sources."""
        jobs = []
        jobs.extend(self.fetch_rss_feeds())
        # HN Who is Hiring runs monthly — only on first day of month
        if datetime.now(timezone.utc).day == 1:
            jobs.extend(self.fetch_hn_who_is_hiring())
        return jobs
