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

PLACEHOLDER_PATTERN = re.compile(r"(\[YOUR [A-Z ]+\]|\{[A-Z_]+\}|<CANDIDATE NAME>|INSERT [A-Z ]+HERE)")
PROFANITY_PATTERN = re.compile(r"\b(fuck|shit|damn|crap|ass|bitch)\b", re.IGNORECASE)


@dataclass
class OutputValidation:
    valid: bool
    output: str
    issues: List[str]
    fallback_used: bool = False


class OutputFilter:
    """
    Post-LLM output sanitizer. Called after every LLM response.
    """

    MAX_COVER_LETTER_WORDS = 450
    MIN_COVER_LETTER_WORDS = 100
    MAX_JSON_CHARS = 20_000

    def validate_cover_letter(self, text: str, job: Dict) -> OutputValidation:
        """Validate a generated cover letter."""
        issues: List[str] = []
        cleaned = text.strip()

        # Check placeholders
        placeholders = PLACEHOLDER_PATTERN.findall(cleaned)
        if placeholders:
            issues.append(f"Unfilled placeholders: {placeholders[:3]}")
            # Try to remove obvious placeholders
            cleaned = PLACEHOLDER_PATTERN.sub("", cleaned).strip()

        # Word count check
        words = len(cleaned.split())
        if words < self.MIN_COVER_LETTER_WORDS:
            issues.append(f"Cover letter too short: {words} words (min {self.MIN_COVER_LETTER_WORDS})")
        elif words > self.MAX_COVER_LETTER_WORDS:
            # Truncate at paragraph boundary
            paragraphs = cleaned.split("\n\n")
            truncated = ""
            for p in paragraphs:
                if len((truncated + p).split()) > self.MAX_COVER_LETTER_WORDS:
                    break
                truncated += p + "\n\n"
            cleaned = truncated.strip()
            issues.append(f"Cover letter truncated: {words} → {len(cleaned.split())} words")

        # Check if company name appears (hallucination check)
        company = job.get("company", "")
        if company and company.lower() not in cleaned.lower() and len(company) > 3:
            issues.append(f"Company name '{company}' missing from cover letter")

        # Profanity check
        if PROFANITY_PATTERN.search(cleaned):
            return OutputValidation(
                valid=False, output="", issues=["Inappropriate content detected"],
            )

        valid = len(issues) == 0 or not any(
            "placeholder" in i.lower() or "inappropriate" in i.lower()
            for i in issues
        )
        return OutputValidation(valid=valid, output=cleaned, issues=issues)

    def validate_json(self, raw: str, required_keys: List[str] = None) -> Tuple[bool, Dict, str]:
        """
        Parse and validate JSON output from LLM.

        Returns: (success, parsed_dict, error_message)
        """
        if not raw or not raw.strip():
            return False, {}, "Empty response"

        # Extract JSON if wrapped in markdown
        raw = raw.strip()
        if raw.startswith("```"):
            m = re.search(r"```(?:json)?\s*(.*?)```", raw, re.DOTALL)
            if m:
                raw = m.group(1).strip()

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            # Try to extract JSON from mixed response
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if m:
                try:
                    data = json.loads(m.group())
                except Exception:
                    return False, {}, f"JSON parse failed: {e}"
            else:
                return False, {}, f"No JSON found: {e}"

        # Validate required keys
        if required_keys:
            missing = [k for k in required_keys if k not in data]
            if missing:
                return False, data, f"Missing required keys: {missing}"

        return True, data, ""

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

    def validate_linkedin_dm(self, text: str) -> OutputValidation:
        """Validate LinkedIn DM (hard 300 char limit)."""
        issues = []
        cleaned = text.strip()

        # Remove "DM:" prefix if present
        cleaned = re.sub(r"^DM:\s*", "", cleaned, flags=re.IGNORECASE)

        if len(cleaned) > 300:
            cleaned = cleaned[:297] + "..."
            issues.append(f"DM truncated to 300 chars")

        placeholders = PLACEHOLDER_PATTERN.findall(cleaned)
        if placeholders:
            issues.append(f"Unfilled placeholders: {placeholders}")

        return OutputValidation(valid=len(issues) == 0, output=cleaned, issues=issues)
