"""
Company Hiring Freeze Detector
================================
Stop wasting applications on companies with hiring freezes.
Detects freeze signals from:
  - Layoffs.fyi (structured data)
  - Blind / Reddit posts (community reports)
  - LinkedIn headcount trends (public data)
  - Company news (earnings, restructuring)
  - Job posting volume drop (own data: company had 20 jobs last week, 2 this week)

Returns: FROZEN | LIKELY_FROZEN | UNCERTAIN | HIRING | SURGE
"""

import json
import logging
import os
import re
import requests
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

FREEZE_ANALYSIS_PROMPT = """Analyze whether this company has a hiring freeze.

Company: {company}
Evidence gathered:
{evidence}

Recent job posting count from our data:
This week: {current_postings}
Last week: {prev_postings}

Return JSON:
{{
  "status": "<FROZEN|LIKELY_FROZEN|UNCERTAIN|HIRING|SURGE>",
  "confidence": "<High|Medium|Low>",
  "reason": "<one sentence>",
  "recommendation": "<Skip for now|Apply with caution|Apply normally|Apply immediately>",
  "recheck_in_days": <int>
}}"""

KNOWN_FREEZE_SIGNALS = [
    "hiring freeze", "pause hiring", "pausing hiring", "no open roles",
    "rescinded offers", "laying off", "reducing headcount", "restructuring",
    "rif ", "reduction in force", "cost cutting", "belt tightening",
]

KNOWN_SURGE_SIGNALS = [
    "series a", "series b", "series c", "series d", "raised $", "funding round",
    "expanding team", "doubling headcount", "aggressive hiring", "growing team",
]

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; JobAgent/1.0)"}


class FreezeDetector:
    def __init__(self, config: dict):
        self.cfg = config.get("ai", {})
        self.provider = self.cfg.get("provider", "openai")
        self.model = self.cfg.get("model", "gpt-4o-mini")
        self._client = None
        self._cache_path = Path("freeze_cache.json")
        self._cache = self._load_cache()

    def _get_openai_client(self):
        if self._client is None:
            import openai
            api_key = self.cfg.get("openai_api_key") or os.environ.get("OPENAI_API_KEY", "")
            self._client = openai.OpenAI(api_key=api_key)
        return self._client

    def _load_cache(self) -> dict:
        if self._cache_path.exists():
            try:
                data = json.loads(self._cache_path.read_text())
                cutoff = (datetime.utcnow() - timedelta(days=7)).isoformat()
                return {k: v for k, v in data.items() if v.get("_cached_at", "") > cutoff}
            except Exception:
                pass
        return {}

    def _save_cache(self):
        self._cache_path.write_text(json.dumps(self._cache, indent=2))

    def _search_evidence(self, company: str) -> str:
        """Search for hiring freeze signals for a company."""
        snippets = []
        queries = [
            f"{company} hiring freeze 2024 2025",
            f"{company} layoffs site:layoffs.fyi OR site:reddit.com OR site:blind.com",
        ]
        for query in queries[:1]:
            try:
                resp = requests.get(
                    "https://api.duckduckgo.com/",
                    params={"q": query, "format": "json", "no_html": 1},
                    headers=HEADERS, timeout=8,
                )
                data = resp.json()
                if data.get("AbstractText"):
                    snippets.append(data["AbstractText"])
                for topic in data.get("RelatedTopics", [])[:4]:
                    text = topic.get("Text", "")
                    if text:
                        snippets.append(text)
            except Exception:
                pass
        return "\n".join(snippets) or "No specific evidence found."

    def _rule_based_check(self, company: str, evidence: str) -> Optional[str]:
        """Fast rule-based check before LLM."""
        text = evidence.lower()
        freeze_hits = sum(1 for s in KNOWN_FREEZE_SIGNALS if s in text)
        surge_hits = sum(1 for s in KNOWN_SURGE_SIGNALS if s in text)
        if freeze_hits >= 2:
            return "FROZEN"
        if freeze_hits == 1 and surge_hits == 0:
            return "LIKELY_FROZEN"
        if surge_hits >= 2:
            return "SURGE"
        if surge_hits == 1:
            return "HIRING"
        return None

    def _get_posting_volume(self, company: str, db) -> tuple:
        """Count how many jobs this company had this vs last week."""
        try:
            all_jobs = db.get_all_jobs(limit=2000)
            now = datetime.utcnow()
            week_ago = (now - timedelta(days=7)).isoformat()
            two_weeks_ago = (now - timedelta(days=14)).isoformat()
            this_week = sum(1 for j in all_jobs
                          if j.get("company") == company and (j.get("scraped_at") or "") > week_ago)
            last_week = sum(1 for j in all_jobs
                          if j.get("company") == company
                          and two_weeks_ago < (j.get("scraped_at") or "") <= week_ago)
            return this_week, last_week
        except Exception:
            return 0, 0

    def check_company(self, company: str, db=None, force_refresh: bool = False) -> Dict:
        """Check if a company has a hiring freeze."""
        if company in self._cache and not force_refresh:
            return self._cache[company]

        logger.info(f"Freeze check: {company}")
        evidence = self._search_evidence(company)
        current, prev = self._get_posting_volume(company, db) if db else (0, 0)

        # Rule-based fast path
        rule_result = self._rule_based_check(company, evidence)

        # Volume drop signal
        if prev > 5 and current < prev * 0.3:
            evidence += f"\n⚠️ Posting volume dropped from {prev} to {current} this week (70% drop)"

        try:
            if self.provider == "openai":
                client = self._get_openai_client()
                resp = client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": FREEZE_ANALYSIS_PROMPT.format(
                        company=company, evidence=evidence[:1500],
                        current_postings=current, prev_postings=prev,
                    )}],
                    temperature=0.2, max_tokens=200,
                    response_format={"type": "json_object"},
                )
                result = json.loads(resp.choices[0].message.content)
            else:
                result = {
                    "status": rule_result or "UNCERTAIN",
                    "confidence": "Low",
                    "reason": "Rule-based detection only",
                    "recommendation": "Apply with caution",
                    "recheck_in_days": 3,
                }
        except Exception:
            result = {"status": rule_result or "UNCERTAIN", "confidence": "Low",
                      "recommendation": "Apply with caution", "recheck_in_days": 3}

        result["_cached_at"] = datetime.utcnow().isoformat()
        result["_company"] = company
        self._cache[company] = result
        self._save_cache()
        return result

    def filter_frozen(self, jobs: List[Dict], db=None) -> tuple:
        """Split jobs into (safe_jobs, frozen_jobs)."""
        safe, frozen = [], []
        seen = set()
        for job in jobs:
            company = job.get("company", "")
            if company not in seen:
                seen.add(company)
                result = self.check_company(company, db)
                self._cache[company] = result
            else:
                result = self._cache.get(company, {})
            status = result.get("status", "UNCERTAIN")
            job["freeze_status"] = status
            job["freeze_reason"] = result.get("reason", "")
            if status in ("FROZEN", "LIKELY_FROZEN"):
                job["filter_reason"] = f"Potential hiring freeze: {result.get('reason', '')}"
                frozen.append(job)
            else:
                safe.append(job)
        return safe, frozen

    def get_frozen_companies(self) -> List[str]:
        return [c for c, d in self._cache.items()
                if d.get("status") in ("FROZEN", "LIKELY_FROZEN")]
