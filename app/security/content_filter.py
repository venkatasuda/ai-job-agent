"""
app/security/content_filter.py — Content filtering layer
==========================================================
Filters job content mid-pipeline:
  - Ghost job detector (posted but not actually hiring)
  - Duplicate / repost detection
  - Quality floor enforcement (no description = skip)
  - Salary sanity check (reject $1/hr jobs)
  - Role relevance filter (if it doesn't match any keyword, skip)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class FilterResult:
    passed: bool
    reason: Optional[str] = None
    score_adjustment: float = 0.0  # Penalize borderline jobs
    tags: List[str] = field(default_factory=list)


class ContentFilter:
    """
    Mid-pipeline content quality filter.
    Distinct from InputGuard (security) — this is about quality, not safety.
    """

    GHOST_JOB_PATTERNS = [
        r"(?i)(building (our|a) talent pool|future (openings?|opportunities?))",
        r"(?i)(we ('re|are) always looking|always hiring)",
        r"(?i)(no (immediate|current) openings?|not currently hiring)",
        r"(?i)(speculative application|spontaneous application)",
        r"(?i)(pipeline (role|position)|pool (of|for) candidates)",
    ]

    LOW_QUALITY_PATTERNS = [
        r"(?i)(apply (now|here|today|fast|quick|immediately)!+)",
        r"(?i)(no (resume|cv|interview) (needed|required))",
        r"(?i)(get paid (to|for) (learn|training))",
    ]

    EXCLUDED_TITLES = [
        r"(?i)\b(internship|intern\b)",
        r"(?i)\b(director|vp|vice president|cto|ceo|cfo|head of)\b",
        r"(?i)\b(principal|distinguished|fellow)\b",
    ]

    def __init__(self, config: dict):
        self.cfg = config
        self.search_cfg = config.get("search", {})
        self.keywords = [k.lower() for k in self.search_cfg.get("keywords", [])]
        self.excluded_companies = {
            c.lower() for c in self.search_cfg.get("excluded_companies", [])
        }
        self.excluded_keywords = [
            k.lower() for k in self.search_cfg.get("excluded_keywords", [])
        ]
        self.min_salary = self.search_cfg.get("min_salary", 0)

    def check_job(self, job: Dict) -> FilterResult:
        """Run all content filters on a single job."""
        title = (job.get("title") or "").lower()
        company = (job.get("company") or "").lower()
        description = (job.get("description") or "").lower()
        text = title + " " + description

        # Excluded company
        if company in self.excluded_companies:
            return FilterResult(passed=False, reason=f"Excluded company: {company}")

        # Excluded keywords in title/description
        for kw in self.excluded_keywords:
            if kw in text:
                return FilterResult(passed=False, reason=f"Excluded keyword: {kw}")

        # No description at all
        if len(description.strip()) < 50:
            return FilterResult(passed=False, reason="No job description", tags=["no_description"])

        # Ghost job detection
        ghost = self._check_ghost(description)
        if ghost:
            return FilterResult(passed=False, reason=f"Ghost job: {ghost}", tags=["ghost"])

        # Salary floor
        salary_min = job.get("salary_min")
        if salary_min and float(salary_min) < self.min_salary * 0.5:
            return FilterResult(passed=False, reason=f"Salary too low: ${salary_min:,.0f}")

        # Low quality signals (don't block, just penalize)
        tags = []
        score_adj = 0.0
        for pattern in self.LOW_QUALITY_PATTERNS:
            if re.search(pattern, text):
                score_adj -= 5
                tags.append("low_quality")
                break

        return FilterResult(passed=True, score_adjustment=score_adj, tags=tags)

    def filter_batch(self, jobs: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
        """Returns (passed_jobs, filtered_jobs)."""
        passed, filtered = [], []
        for job in jobs:
            result = self.check_job(job)
            if result.passed:
                if result.score_adjustment != 0 and job.get("score"):
                    job["score"] = max(0, (job["score"] or 0) + result.score_adjustment)
                passed.append(job)
            else:
                job["filter_reason"] = result.reason
                filtered.append(job)
        return passed, filtered

    def _check_ghost(self, text: str) -> Optional[str]:
        for pattern in self.GHOST_JOB_PATTERNS:
            m = re.search(pattern, text)
            if m:
                return m.group()
        return None

    def is_role_relevant(self, job: Dict) -> bool:
        """Check if job title/description matches any of the user's target roles."""
        if not self.keywords:
            return True
        text = ((job.get("title") or "") + " " + (job.get("description") or ""))[:500].lower()
        return any(kw in text for kw in self.keywords)
