"""
Job Description Summarizer
============================
Converts long, jargon-heavy job descriptions into a clean 30-second read.

Output:
  - TL;DR (2 sentences)
  - What you'd actually do day-to-day (3 bullets)
  - Must-haves vs. nice-to-haves (separated clearly)
  - Red flags / yellow flags
  - Salary decoded (if equity/benefits are buried)
  - Interview likely format (based on tech stack + role)
  - "Worth applying?" quick verdict

This also powers the dashboard job cards — long JDs get summarized
before display so users can scan faster.
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

JD_SUMMARY_PROMPT = """Summarize this job description for a job seeker. Be direct and specific.

Job: {title} at {company}
Full JD:
{jd}

Return JSON:
{{
  "tldr": "<2 sentence summary — what the job actually is>",
  "day_to_day": ["<task 1>", "<task 2>", "<task 3>"],
  "must_haves": ["<requirement 1>", "<requirement 2>", "<requirement 3>"],
  "nice_to_haves": ["<nice 1>", "<nice 2>"],
  "red_flags": ["<flag 1>"],
  "green_flags": ["<flag 1>"],
  "equity_decoded": "<what the equity/comp structure means in plain English>",
  "interview_format": "<likely interview format based on role/tech stack>",
  "team_size_hint": "<any hints about team size>",
  "worth_applying": "<Yes|Maybe|No>",
  "worth_applying_reason": "<one sentence>"
}}"""

# Patterns to detect red flags automatically (before LLM)
RED_FLAG_PATTERNS = [
    (r"(?i)wear many hats", "⚠️ 'Wear many hats' = understaffed"),
    (r"(?i)fast.?paced", "⚠️ 'Fast-paced' often means chaotic"),
    (r"(?i)rockstar|ninja|wizard|guru", "⚠️ Cringe job titles = culture red flag"),
    (r"(?i)unlimited pto", "⚠️ 'Unlimited PTO' often means less actual PTO taken"),
    (r"(?i)equity in lieu of salary|below market", "⚠️ Below-market comp"),
    (r"(?i)background check required for clearance", "ℹ️ Security clearance required"),
    (r"(?i)must be available 24/7|on call", "⚠️ 24/7 availability expected"),
    (r"(?i)no remote|must be onsite|return to office", "ℹ️ No remote work"),
    (r"(?i)bootstrap|self.?funded|pre.?revenue", "⚠️ Early-stage startup, less job security"),
]

GREEN_FLAG_PATTERNS = [
    (r"(?i)series [bc]|well.?funded|backed by", "✅ Well-funded company"),
    (r"(?i)work from (anywhere|home|remote)", "✅ Remote-friendly culture"),
    (r"(?i)401k match|equity|rsu|stock", "✅ Compensation includes equity"),
    (r"(?i)learning budget|conference|education", "✅ Invests in employee growth"),
    (r"(?i)parental leave|maternity|paternity", "✅ Family-friendly policies"),
    (r"(?i)engineering blog|open source", "✅ Values engineering excellence"),
]


class JDSummarizer:
    def __init__(self, config: dict):
        self.cfg = config.get("ai", {})
        self.provider = self.cfg.get("provider", "openai")
        self.model = self.cfg.get("model", "gpt-4o-mini")
        self._client = None
        self._cache_path = Path("jd_summary_cache.json")
        self._cache = self._load_cache()

    def _get_openai_client(self):
        if self._client is None:
            import openai
            api_key = self.cfg.get("openai_api_key") or os.environ.get("OPENAI_API_KEY", "")
            self._client = openai.OpenAI(api_key=api_key)
        return self._client

    def _llm_json(self, prompt: str) -> dict:
        try:
            if self.provider == "openai":
                client = self._get_openai_client()
                resp = client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3, max_tokens=700,
                    response_format={"type": "json_object"},
                )
                return json.loads(resp.choices[0].message.content)
            elif self.provider == "gemini":
                import google.generativeai as genai
                api_key = self.cfg.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY", "")
                genai.configure(api_key=api_key)
                text = genai.GenerativeModel(self.model or "gemini-1.5-flash").generate_content(prompt).text
                m = re.search(r'\{.*\}', text, re.DOTALL)
                return json.loads(m.group()) if m else {}
        except Exception as e:
            logger.warning(f"JD summarizer LLM error: {e}")
        return {}

    def _load_cache(self) -> dict:
        if self._cache_path.exists():
            try:
                return json.loads(self._cache_path.read_text())
            except Exception:
                pass
        return {}

    def _save_cache(self):
        # Keep last 500 summaries
        if len(self._cache) > 500:
            keys = list(self._cache.keys())
            for k in keys[:-500]:
                del self._cache[k]
        self._cache_path.write_text(json.dumps(self._cache, indent=2))

    def _get_cache_key(self, job: Dict) -> str:
        import hashlib
        jd = (job.get("description") or "")[:200]
        return hashlib.md5(jd.encode()).hexdigest()[:12]

    def _rule_based_flags(self, jd: str) -> tuple:
        red, green = [], []
        for pattern, label in RED_FLAG_PATTERNS:
            if re.search(pattern, jd):
                red.append(label)
        for pattern, label in GREEN_FLAG_PATTERNS:
            if re.search(pattern, jd):
                green.append(label)
        return red, green

    def _rule_based_analysis(self, jd: str) -> dict:
        """Rule-based red/green flag analysis as a dict (no LLM)."""
        red, green = self._rule_based_flags(jd)
        return {"red_flags": red, "green_flags": green}

    def summarize(self, job: Dict) -> Dict:
        """Summarize a job description. Returns dict with all fields."""
        cache_key = self._get_cache_key(job)
        if cache_key in self._cache:
            return self._cache[cache_key]

        jd = job.get("description") or ""
        if len(jd) < 50:
            return {"tldr": "No description available", "worth_applying": "Maybe"}

        # Rule-based flags (free, no LLM)
        rule_red, rule_green = self._rule_based_flags(jd)

        # LLM summary
        result = self._llm_json(JD_SUMMARY_PROMPT.format(
            title=job.get("title", "Role"),
            company=job.get("company", "Company"),
            jd=jd[:3000],
        ))

        # Merge rule-based with LLM
        result.setdefault("red_flags", [])
        result.setdefault("green_flags", [])
        result["red_flags"] = rule_red + [f for f in result["red_flags"] if f not in rule_red]
        result["green_flags"] = rule_green + [f for f in result["green_flags"] if f not in rule_green]

        if not result:
            result = {
                "tldr": f"{job.get('title')} role at {job.get('company')}. See full JD.",
                "red_flags": rule_red, "green_flags": rule_green,
                "worth_applying": "Maybe",
            }

        self._cache[cache_key] = result
        self._save_cache()
        return result

    def summarize_batch(self, jobs: List[Dict], threshold: int = 60) -> List[Dict]:
        """Summarize JDs for jobs above threshold score."""
        for job in jobs:
            if (job.get("score") or 0) >= threshold and not job.get("jd_summary"):
                try:
                    job["jd_summary"] = self.summarize(job)
                except Exception as e:
                    logger.warning(f"JD summarize failed for {job.get('title')}: {e}")
        return jobs

    def get_quick_verdict(self, job: Dict) -> str:
        """One-line verdict: should I apply?"""
        summary = self.summarize(job)
        verdict = summary.get("worth_applying", "Maybe")
        reason = summary.get("worth_applying_reason", "")
        tldr = summary.get("tldr", "")
        emoji = {"Yes": "✅", "Maybe": "🤔", "No": "❌"}.get(verdict, "❓")
        return f"{emoji} {verdict}: {reason or tldr[:100]}"
