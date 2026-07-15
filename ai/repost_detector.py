"""
Repost & Scam Detector — inspired by career-ops' posting-legitimacy check.

Filters out:
  - Ghost jobs (postings that never get filled, recycled to inflate pipeline)
  - Reposts (same job seen recently under a slightly different title)
  - Scam postings (MLM, commission-only, fake remote, suspicious patterns)
  - Staffing agency spam (generic postings for multiple clients)

Running this BEFORE AI scoring saves significant API cost.
"""

import re
import logging
import hashlib
from typing import List, Dict, Tuple

logger = logging.getLogger(__name__)

SCAM_TITLE_PATTERNS = [
    r"unlimited earning",
    r"be your own boss",
    r"work from home.{0,20}no experience",
    r"earn \$\d+.{0,10}(hour|day|week) from home",
    r"network marketing",
    r"direct sales",
    r"independent contractor.{0,30}commission",
    r"multi.?level",
    r"mlm",
    r"pyramid",
    r"make money (fast|quick|easy)",
    r"passive income",
]

SCAM_DESC_PATTERNS = [
    r"no experience (required|needed)",
    r"commission[\s-]?only",
    r"1099 only",
    r"door[- ]?to[- ]?door",
    r"cold calling required",
    r"must (own|have) (a )?car",
    r"upfront (fee|payment|investment)",
    r"purchase (starter|kit|product)",
    r"unlimited (earning|income) potential",
    r"join our team of (independent|self-employed)",
    r"\$\d{4,5}\+? per (week|day).{0,30}(from home|remote)",
]

GHOST_JOB_SIGNALS = [
    r"(various|multiple|several) (clients|companies|employers)",
    r"confidential (employer|company|client)",
    r"we are looking for (a |an )?(talented|motivated|passionate|driven|dynamic)",
    r"competitive (salary|compensation|package) and (benefits|perks)",
]

STAFFING_AGENCY_PATTERNS = [
    r"(staffing|recruiting|placement|temp) (agency|firm|company|group)",
    r"on behalf of (our|the) client",
    r"client of (ours|mine)",
    r"contract.{0,20}(to hire|to perm|to permanent)",
    r"w2 (contract|position|role)",
]

SPAM_TITLE_KEYWORDS = [
    "hiring now", "immediate opening", "urgent hire", "multiple openings",
    "now hiring", "immediately available", "open to all majors",
]


def _fingerprint(job: Dict) -> str:
    title = re.sub(r"[^a-z0-9\s]", "", (job.get("title") or "").lower())
    company = re.sub(r"[^a-z0-9\s]", "", (job.get("company") or "").lower())
    location = re.sub(r"[^a-z0-9\s]", "", (job.get("location") or "").lower())
    for word in ["senior", "sr", "jr", "junior", "lead", "staff", "principal"]:
        title = re.sub(rf"\b{word}\b", "", title)
    return hashlib.md5(f"{company}|{title.strip()}|{location.strip()}".encode()).hexdigest()


class RepostDetector:
    def __init__(self, config: dict = None):
        self.config = config or {}
        self._seen_fingerprints: set = set()

    def _check_scam(self, job: Dict) -> Tuple[bool, str]:
        title = (job.get("title") or "").lower()
        desc = (job.get("description") or "").lower()
        for pat in SCAM_TITLE_PATTERNS:
            if re.search(pat, title):
                return True, f"Scam title: '{pat}'"
        for pat in SCAM_DESC_PATTERNS:
            if re.search(pat, desc):
                return True, f"Scam description: '{pat}'"
        for kw in SPAM_TITLE_KEYWORDS:
            if kw in title:
                return True, f"Spam keyword: '{kw}'"
        return False, ""

    def _check_staffing_agency(self, job: Dict) -> Tuple[bool, str]:
        combined = f"{job.get('title','')} {job.get('company','')} {(job.get('description') or '')[:500]}".lower()
        for pat in STAFFING_AGENCY_PATTERNS:
            if re.search(pat, combined):
                return True, f"Staffing agency: '{pat}'"
        return False, ""

    def _check_ghost_job(self, job: Dict) -> Tuple[bool, str]:
        desc = (job.get("description") or "").strip()
        if len(desc) < 100:
            return True, "Description too short (<100 chars)"
        ghost_count = sum(1 for pat in GHOST_JOB_SIGNALS if re.search(pat, desc.lower()))
        if ghost_count >= 2:
            return True, f"Multiple ghost job signals ({ghost_count})"
        return False, ""

    def _check_repost(self, job: Dict) -> Tuple[bool, str]:
        fp = _fingerprint(job)
        if fp in self._seen_fingerprints:
            return True, "Duplicate/repost seen this session"
        self._seen_fingerprints.add(fp)
        return False, ""

    def classify(self, job: Dict) -> Tuple[bool, str]:
        for check in [self._check_repost, self._check_scam, self._check_staffing_agency, self._check_ghost_job]:
            skip, reason = check(job)
            if skip:
                return True, reason
        return False, ""

    def filter_jobs(self, jobs: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
        clean, filtered = [], []
        for job in jobs:
            skip, reason = self.classify(job)
            if skip:
                job["filter_reason"] = reason
                filtered.append(job)
            else:
                clean.append(job)
        pct = len(filtered) / len(jobs) * 100 if jobs else 0
        logger.info(f"Repost/Scam filter: {len(filtered)}/{len(jobs)} removed ({pct:.0f}%) → {len(clean)} clean")
        return clean, filtered
