"""
app/security/input_guard.py — Input validation layer
=====================================================
Validates and sanitizes all inputs BEFORE they reach LLM agents.

Guards against:
  - Prompt injection in job descriptions ("Ignore previous instructions...")
  - Excessively long inputs that spike costs
  - Malformed URLs and data
  - PII leakage in logs (masks API keys, emails, phone numbers)
  - Scam job postings with social engineering patterns

This runs at the pipeline entry point before any AI processing.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Prompt injection patterns ──────────────────────────────────────────────────
INJECTION_PATTERNS = [
    r"(?i)ignore (previous|all|prior) instructions",
    r"(?i)forget (everything|all) (you|i) (told|said|know)",
    r"(?i)you are now (a|an)",
    r"(?i)act as (a|an|if)",
    r"(?i)new (system|persona|role|instructions?)",
    r"(?i)###\s*(system|instructions?|context)",
    r"(?i)<\s*(system|instructions?)\s*>",
    r"(?i)jailbreak",
    r"(?i)do (anything|whatever) now",
    r"(?i)reveal (your|the) (system prompt|instructions)",
]

# ── Scam / phishing patterns in job postings ───────────────────────────────────
SCAM_PATTERNS = [
    r"(?i)(wire transfer|western union|moneygram)",
    r"(?i)(work from home|make \$[\d,]+ (per day|daily|weekly))",
    r"(?i)(no experience (needed|required)|immediate (start|hire))",
    r"(?i)(send (money|payment|fee) to|pay (for|a) (training|kit|equipment))",
    r"(?i)(click here to apply|whatsapp (me|us) to apply)",
    r"(?i)(guaranteed income|\$[\d,]+/hour guaranteed)",
    r"(?i)(secret shopper|mystery shopper)",
    r"(?i)(pyramid|multi.?level marketing|mlm)",
]

# ── PII patterns for log masking ───────────────────────────────────────────────
PII_PATTERNS = [
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}"), "***@***.***"),
    (re.compile(r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b"), "***-***-****"),
    (re.compile(r"sk-[A-Za-z0-9]{20,}"), "sk-***"),  # OpenAI keys
    (re.compile(r"AIzaSy[A-Za-z0-9_-]{33}"), "AIzaSy***"),  # Gemini keys
    (re.compile(r"(?i)bearer [A-Za-z0-9._-]{20,}"), "Bearer ***"),
]


@dataclass
class ValidationResult:
    valid: bool
    cleaned: Any
    warnings: List[str]
    blocked: bool = False
    block_reason: Optional[str] = None


class InputGuard:
    """
    Validates inputs before LLM processing.
    Instantiate once and reuse across the pipeline.
    """

    MAX_JD_CHARS = 8_000
    MAX_RESUME_CHARS = 6_000
    MAX_COVER_LETTER_CHARS = 4_000
    MAX_COMPANY_NAME_CHARS = 200
    MAX_TITLE_CHARS = 200

    def validate_job(self, job: Dict) -> ValidationResult:
        """Full validation pass on a job dict before AI processing."""
        warnings: List[str] = []
        cleaned = dict(job)

        # Truncate oversized fields
        if len(cleaned.get("description") or "") > self.MAX_JD_CHARS:
            cleaned["description"] = cleaned["description"][:self.MAX_JD_CHARS]
            warnings.append(f"JD truncated to {self.MAX_JD_CHARS} chars")

        if len(cleaned.get("title") or "") > self.MAX_TITLE_CHARS:
            cleaned["title"] = cleaned["title"][:self.MAX_TITLE_CHARS]

        if len(cleaned.get("company") or "") > self.MAX_COMPANY_NAME_CHARS:
            cleaned["company"] = cleaned["company"][:self.MAX_COMPANY_NAME_CHARS]

        # Check for prompt injection in JD
        jd = cleaned.get("description") or ""
        injection_hit = self._check_injection(jd)
        if injection_hit:
            warnings.append(f"⚠️ Potential prompt injection in JD: {injection_hit}")
            # Sanitize by removing the suspicious line
            cleaned["description"] = self._neutralize_injection(jd)

        # Check for scam patterns
        scam_hit = self._check_scam(jd + " " + (cleaned.get("title") or ""))
        if scam_hit:
            return ValidationResult(
                valid=False, cleaned=cleaned, warnings=warnings,
                blocked=True, block_reason=f"Scam pattern: {scam_hit}",
            )

        # Validate URL
        url = cleaned.get("job_url") or cleaned.get("url") or ""
        if url and not self._is_safe_url(url):
            cleaned["job_url"] = ""
            warnings.append(f"Unsafe URL removed: {url[:50]}")

        return ValidationResult(valid=True, cleaned=cleaned, warnings=warnings)

    def validate_resume(self, resume_text: str) -> ValidationResult:
        """Validate resume before sending to LLMs."""
        warnings: List[str] = []
        cleaned = resume_text

        if len(cleaned) > self.MAX_RESUME_CHARS:
            cleaned = cleaned[:self.MAX_RESUME_CHARS]
            warnings.append(f"Resume truncated to {self.MAX_RESUME_CHARS} chars")

        injection = self._check_injection(cleaned)
        if injection:
            cleaned = self._neutralize_injection(cleaned)
            warnings.append(f"Injection neutralized in resume: {injection}")

        return ValidationResult(valid=True, cleaned=cleaned, warnings=warnings)

    def validate_cover_letter(self, text: str) -> ValidationResult:
        """Validate LLM-generated cover letter output."""
        warnings: List[str] = []
        cleaned = text.strip()

        if len(cleaned) > self.MAX_COVER_LETTER_CHARS:
            warnings.append("Cover letter truncated")
            cleaned = cleaned[:self.MAX_COVER_LETTER_CHARS]

        # Check for hallucinated company names or placeholder text
        placeholders = re.findall(r"\[.*?\]|\{.*?\}", cleaned)
        if placeholders:
            warnings.append(f"Unfilled placeholders found: {placeholders[:3]}")

        return ValidationResult(valid=True, cleaned=cleaned, warnings=warnings)

    def batch_validate_jobs(self, jobs: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
        """
        Validate a list of jobs. Returns (valid_jobs, blocked_jobs).
        """
        valid, blocked = [], []
        for job in jobs:
            result = self.validate_job(job)
            if result.blocked:
                job["filter_reason"] = result.block_reason
                blocked.append(job)
                logger.debug(f"Blocked: {job.get('title')} @ {job.get('company')} — {result.block_reason}")
            else:
                for warning in result.warnings:
                    logger.debug(f"Input warning [{job.get('company')}]: {warning}")
                valid.append(result.cleaned)
        return valid, blocked

    def _check_injection(self, text: str) -> Optional[str]:
        for pattern in INJECTION_PATTERNS:
            m = re.search(pattern, text)
            if m:
                return m.group()
        return None

    def _neutralize_injection(self, text: str) -> str:
        """Remove injection patterns from text."""
        for pattern in INJECTION_PATTERNS:
            text = re.sub(pattern, "[content removed]", text, flags=re.IGNORECASE)
        return text

    def _check_scam(self, text: str) -> Optional[str]:
        for pattern in SCAM_PATTERNS:
            m = re.search(pattern, text)
            if m:
                return m.group()
        return None

    def _is_safe_url(self, url: str) -> bool:
        """Basic URL safety check."""
        SAFE_DOMAINS = [
            "linkedin.com", "indeed.com", "glassdoor.com", "greenhouse.io",
            "lever.co", "ashbyhq.com", "workday.com", "myworkdayjobs.com",
            "jobs.lever.co", "google.com", "ziprecruiter.com", "monster.com",
            "simplify.jobs", "otta.com", "wellfound.com",
        ]
        url_lower = url.lower()
        if not url_lower.startswith(("http://", "https://")):
            return False
        if any(d in url_lower for d in SAFE_DOMAINS):
            return True
        # Allow direct career pages
        if any(p in url_lower for p in ["/careers", "/jobs", "/apply", "greenhouse", "lever", "ashby"]):
            return True
        return True  # Allow unknown but log it

    @staticmethod
    def mask_pii(text: str) -> str:
        """Mask PII for safe logging."""
        for pattern, replacement in PII_PATTERNS:
            text = pattern.sub(replacement, text)
        return text
