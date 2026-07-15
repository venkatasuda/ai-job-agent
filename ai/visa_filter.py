"""
Visa Sponsorship Filter
========================
Critical for international Masters graduates on F-1/OPT/H1B.
Detects whether a job offers, is silent about, or explicitly denies sponsorship.

Categories:
  SPONSORS     — explicitly mentions H1B/OPT/sponsorship support
  SILENT       — no mention either way (apply, ask during screening)
  NO_SPONSOR   — explicitly says "no sponsorship", "must be authorized", "citizens only"
  UNCERTAIN    — mixed signals, needs manual check

Also detects:
  - CPT eligibility (for F-1 students doing internships)
  - Security clearance requirements (typically blocks international candidates)
  - "Authorized to work" phrasing variants
"""

import re
from typing import Dict, List, Tuple

# Patterns that CONFIRM sponsorship
SPONSORS_PATTERNS = [
    r"visa\s+sponsor",
    r"h[\-\s]?1b",
    r"h1[\-\s]?b\s+sponsor",
    r"opt\s+sponsor",
    r"cpt\s+eligible",
    r"will\s+sponsor",
    r"sponsorship\s+(is\s+)?available",
    r"open\s+to\s+sponsorship",
    r"support\s+(visa|immigration)",
    r"immigration\s+support",
    r"relocation\s+.{0,30}visa",
]

# Patterns that DENY sponsorship
NO_SPONSOR_PATTERNS = [
    r"no\s+visa\s+sponsor",
    r"not\s+able\s+to\s+sponsor",
    r"cannot\s+sponsor",
    r"unable\s+to\s+(provide\s+)?sponsor",
    r"sponsorship\s+(is\s+)?not\s+(available|offered|provided)",
    r"must\s+be\s+(legally\s+)?(authorized|eligible)\s+to\s+work\s+in\s+the\s+(us|usa|united\s+states)",
    r"(us|u\.s\.)\s+citizen(s)?\s+only",
    r"citizens?\s+or\s+permanent\s+resident",
    r"green\s+card\s+holder",
    r"no\s+sponsorship",
    r"does\s+not\s+offer\s+sponsorship",
    r"applicants?\s+must\s+(already\s+)?be\s+authorized",
    r"without\s+(the\s+need\s+for\s+)?sponsorship",
    r"require(s)?\s+security\s+clearance",  # usually blocks international
    r"secret\s+clearance",
    r"top\s+secret",
    r"ts\/sci",
]

# Companies known to sponsor (commonly updated by community)
KNOWN_SPONSORS = {
    "google", "meta", "amazon", "microsoft", "apple", "netflix", "uber", "lyft",
    "stripe", "airbnb", "databricks", "openai", "anthropic", "nvidia", "salesforce",
    "linkedin", "twitter", "snap", "pinterest", "dropbox", "atlassian", "shopify",
    "coinbase", "robinhood", "doordash", "instacart", "palantir", "snowflake",
    "datadog", "cloudflare", "twilio", "okta", "zoom", "slack", "github",
    "hugging face", "scale ai", "cohere", "perplexity", "mistral",
}


class VisaFilter:
    def __init__(self, config: dict):
        self.cfg = config
        self.visa_cfg = config.get("visa_filter", {})
        self.require_sponsorship = self.visa_cfg.get("require_sponsorship", False)
        self.exclude_no_sponsor = self.visa_cfg.get("exclude_no_sponsor", True)

    def classify(self, job: Dict) -> Tuple[str, str]:
        """
        Returns (status, reason):
          status: SPONSORS | SILENT | NO_SPONSOR | UNCERTAIN
        """
        text = " ".join([
            job.get("title", ""),
            job.get("description", ""),
            job.get("company", ""),
        ]).lower()

        sponsors_found = [p for p in SPONSORS_PATTERNS if re.search(p, text)]
        no_sponsor_found = [p for p in NO_SPONSOR_PATTERNS if re.search(p, text)]

        company_lower = (job.get("company") or "").lower()
        known_sponsor = any(known in company_lower for known in KNOWN_SPONSORS)

        if no_sponsor_found and not sponsors_found:
            reason = "Explicitly states no sponsorship / must be authorized"
            return "NO_SPONSOR", reason

        if sponsors_found:
            reason = f"Mentions sponsorship support ({sponsors_found[0]})"
            return "SPONSORS", reason

        if no_sponsor_found and sponsors_found:
            reason = "Mixed signals — mentions both sponsorship and restrictions"
            return "UNCERTAIN", reason

        if known_sponsor:
            reason = f"{job.get('company')} is known to sponsor visas historically"
            return "SILENT_LIKELY_OK", reason

        return "SILENT", "No visa mention found — ask during phone screen"

    def filter_jobs(self, jobs: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
        """
        Returns (approved_jobs, filtered_out_jobs).
        If exclude_no_sponsor=True, removes NO_SPONSOR jobs.
        """
        approved = []
        filtered = []

        for job in jobs:
            status, reason = self.classify(job)
            job["visa_status"] = status
            job["visa_reason"] = reason

            if self.exclude_no_sponsor and status == "NO_SPONSOR":
                job["filter_reason"] = f"Visa: {reason}"
                filtered.append(job)
            else:
                approved.append(job)

        return approved, filtered

    def enrich_jobs(self, jobs: List[Dict]) -> List[Dict]:
        """Add visa_status + visa_reason to all jobs without filtering."""
        for job in jobs:
            if not job.get("visa_status"):
                status, reason = self.classify(job)
                job["visa_status"] = status
                job["visa_reason"] = reason
        return jobs
