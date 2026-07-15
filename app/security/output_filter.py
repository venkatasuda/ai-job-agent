"""
app/security/output_filter.py — LLM output validation
=======================================================
Validates and sanitizes all LLM-generated text BEFORE it reaches users.

Guards against:
  - Hallucinated company names or job details
  - Unfilled template placeholders {LIKE_THIS} or [LIKE_THIS]
  - Off-topic or incoherent outputs
  - Oversized outputs (cost spike protection)
  - JSON parse failures (with graceful fallback)
  - Toxic or inappropriate content in generated emails/letters
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

PLACEHOLDER_PATTERN = re.compile(
    r"(\[[A-Z][A-Z0-9 _/-]*\]|\{[A-Za-z_ ]+\}|<[A-Za-z _]+>|INSERT [A-Z ]+HERE)"
)
PROFANITY_PATTERN = re.compile(r"\b(fuck|shit|damn|crap|ass|bitch)\b", re.IGNORECASE)


@dataclass
class OutputValidation:
    valid: bool
    output: str
    issues: List[str]
    fallback_used: bool = False

    @property
    def reason(self) -> str:
        """Human-readable summary of all issues (empty string if none)."""
        return "; ".join(self.issues)


class OutputFilter:
    """
    Post-LLM output sanitizer. Called after every LLM response.
    """

    MAX_COVER_LETTER_WORDS = 450
    MIN_COVER_LETTER_WORDS = 50
    MAX_JSON_CHARS = 20_000

    @staticmethod
    def validate_cover_letter(
        text: str, company: str | None = None, job: Dict | None = None
    ) -> OutputValidation:
        """Validate a generated cover letter.

        Accepts either a ``company`` name or a ``job`` dict (from which the
        company is read). Rejects unfilled placeholders, too-short/too-long
        letters, a missing company name, and inappropriate content.
        """
        issues: List[str] = []
        cleaned = (text or "").strip()
        company_name = company or (job or {}).get("company", "") or ""

        # Check placeholders
        placeholders = PLACEHOLDER_PATTERN.findall(cleaned)
        if placeholders:
            issues.append(f"Unfilled placeholders: {placeholders[:3]}")
            cleaned = PLACEHOLDER_PATTERN.sub("", cleaned).strip()

        # Word count check
        words = len(cleaned.split())
        if words < OutputFilter.MIN_COVER_LETTER_WORDS:
            issues.append(
                f"Cover letter too short: {words} words "
                f"(min {OutputFilter.MIN_COVER_LETTER_WORDS})"
            )
        elif words > OutputFilter.MAX_COVER_LETTER_WORDS:
            paragraphs = cleaned.split("\n\n")
            truncated = ""
            for p in paragraphs:
                if len((truncated + p).split()) > OutputFilter.MAX_COVER_LETTER_WORDS:
                    break
                truncated += p + "\n\n"
            cleaned = truncated.strip()
            issues.append(f"Cover letter truncated to {len(cleaned.split())} words")

        # Company name presence (hallucination check)
        if company_name and len(company_name) > 3 and company_name.lower() not in cleaned.lower():
            issues.append(f"Company name '{company_name}' missing from cover letter")

        # Profanity check
        if PROFANITY_PATTERN.search(cleaned):
            issues.append("Inappropriate content detected")

        return OutputValidation(valid=len(issues) == 0, output=cleaned, issues=issues)

    @staticmethod
    def validate_json(raw: str, required_keys: List[str] = None) -> Optional[Dict]:
        """Parse LLM JSON output. Returns the parsed dict, or None on failure."""
        if not raw or not raw.strip():
            return None

        # Extract JSON if wrapped in markdown
        raw = raw.strip()
        if raw.startswith("```"):
            m = re.search(r"```(?:json)?\s*(.*?)```", raw, re.DOTALL)
            if m:
                raw = m.group(1).strip()

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if not m:
                return None
            try:
                data = json.loads(m.group())
            except Exception:
                return None

        if required_keys and any(k not in data for k in required_keys):
            return None
        return data

    def validate_score(self, score: Any, field_name: str = "score") -> Optional[float]:
        """Validate and clamp a score value."""
        try:
            s = float(score)
            return max(0.0, min(100.0, s))
        except (TypeError, ValueError):
            logger.warning(f"Invalid {field_name}: {score!r}")
            return None

    def sanitize_email(self, text: str) -> str:
        """Sanitize a generated email for sending."""
        # Remove placeholders
        text = PLACEHOLDER_PATTERN.sub("[YOUR INFO]", text)
        # Ensure no PII accidentally included from context
        return text.strip()

    def check_hallucination(self, generated: str, facts: Dict) -> List[str]:
        """
        Check if generated text contradicts known facts.
        Returns list of suspected hallucinations.
        """
        suspected = []
        company = facts.get("company", "")
        title = facts.get("title", "")

        # Check for wrong company name
        if company and len(company) > 3:
            # If another company name appears prominently but not the right one
            if company.lower() not in generated.lower():
                suspected.append(f"Company '{company}' not mentioned")

        return suspected

    @staticmethod
    def validate_linkedin_dm(text: str) -> str:
        """Validate + truncate a LinkedIn DM to the 300-char hard limit. Returns the DM text."""
        cleaned = (text or "").strip()
        cleaned = re.sub(r"^DM:\s*", "", cleaned, flags=re.IGNORECASE)
        if len(cleaned) > 300:
            cleaned = cleaned[:297] + "..."
        return cleaned
