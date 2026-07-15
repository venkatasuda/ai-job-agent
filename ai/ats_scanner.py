"""
ATS Resume Scanner
==================
Before applying, check if your resume will pass the ATS robot.
Most companies use ATS (Applicant Tracking Systems) that auto-reject
resumes missing key terms — even if you're qualified.

Checks:
  - Keyword match % (required vs nice-to-have)
  - Hard missing keywords (likely auto-reject)
  - Soft missing keywords (weakens score)
  - Format warnings (tables, columns, headers ATS can't parse)
  - Recommended adds (safe to inject into bullets)
  - Final ATS score 0-100 with pass/warn/fail verdict
"""

import logging
import os
import re
from typing import Dict, List

logger = logging.getLogger(__name__)

ATS_SCAN_PROMPT = """You are an ATS (Applicant Tracking System) expert who has reviewed 50,000+ resumes.

## Resume
{resume}

## Job Description
Company: {company}
Title: {title}
{description}

Analyze this resume against the JD as an ATS robot would. Return a JSON object:

{{
  "ats_score": <0-100 integer>,
  "verdict": "<PASS|WARN|FAIL>",
  "verdict_reason": "<one sentence why>",
  "required_keywords_found": ["list of required JD keywords found in resume"],
  "required_keywords_missing": ["critical missing keywords — likely causes auto-rejection"],
  "nice_to_have_missing": ["secondary skills missing — weakens score but won't auto-reject"],
  "format_warnings": ["list of format issues that confuse ATS parsers, empty list if none"],
  "quick_fixes": ["specific bullet rewrites or additions to boost score — max 5, be concrete"],
  "title_match": "<STRONG|PARTIAL|WEAK> — does candidate's most recent title match this role?"
}}

Be strict. Real ATS systems are ruthless."""


class ATSScanner:
    def __init__(self, config: dict, resume_text: str):
        self.cfg = config.get("ai", {})
        self.resume = resume_text
        self.provider = self.cfg.get("provider", "openai")
        self.model = self.cfg.get("model", "gpt-4o-mini")
        self._client = None

    def _get_openai_client(self):
        if self._client is None:
            import openai
            api_key = self.cfg.get("openai_api_key") or os.environ.get("OPENAI_API_KEY", "")
            self._client = openai.OpenAI(api_key=api_key)
        return self._client

    def _llm_json(self, prompt: str) -> dict:
        if self.provider == "openai":
            client = self._get_openai_client()
            resp = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=900,
                response_format={"type": "json_object"},
            )
            import json
            return json.loads(resp.choices[0].message.content)
        elif self.provider in ("gemini", "ollama"):
            # Non-OpenAI: get text then parse JSON
            if self.provider == "gemini":
                import google.generativeai as genai
                import json
                api_key = self.cfg.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY", "")
                genai.configure(api_key=api_key)
                text = genai.GenerativeModel(self.model or "gemini-1.5-flash").generate_content(prompt).text.strip()
            else:
                import requests, json
                resp = requests.post("http://localhost:11434/api/generate",
                    json={"model": self.model or "llama3", "prompt": prompt, "stream": False}, timeout=120)
                text = resp.json().get("response", "").strip()
            # Extract JSON from text
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                return json.loads(match.group())
            return {}
        raise ValueError(f"Unknown provider: {self.provider}")

    def scan(self, job: Dict) -> Dict:
        """Run ATS scan on resume vs job. Returns structured result dict."""
        logger.info(f"ATS scan: {job.get('title')} @ {job.get('company')}")
        try:
            result = self._llm_json(ATS_SCAN_PROMPT.format(
                resume=self.resume[:3500],
                company=job.get("company", ""),
                title=job.get("title", ""),
                description=(job.get("description") or "")[:2500],
            ))
            return result
        except Exception as e:
            logger.error(f"ATS scan failed for {job.get('title')}: {e}")
            return {
                "ats_score": 0,
                "verdict": "ERROR",
                "verdict_reason": str(e),
                "required_keywords_missing": [],
                "quick_fixes": [],
            }

    def enrich_jobs(self, jobs: list, threshold: int = 60) -> list:
        """Add ats_scan field to jobs scoring above threshold."""
        for job in jobs:
            if (job.get("score") or 0) >= threshold and not job.get("ats_scan"):
                result = self.scan(job)
                job["ats_scan"] = result
                # Surface the ATS score directly for quick dashboard display
                job["ats_score"] = result.get("ats_score")
                job["ats_verdict"] = result.get("verdict")
        return jobs

    @staticmethod
    def format_report(scan: dict) -> str:
        """Format ATS scan result as readable text for dashboard/alerts."""
        if not scan:
            return "No ATS scan available."
        lines = [
            f"ATS Score: {scan.get('ats_score', '?')}/100  [{scan.get('verdict', '?')}]",
            f"Reason: {scan.get('verdict_reason', '')}",
            f"Title Match: {scan.get('title_match', '?')}",
            "",
        ]
        missing = scan.get("required_keywords_missing", [])
        if missing:
            lines.append(f"CRITICAL MISSING ({len(missing)}): " + ", ".join(missing))

        soft = scan.get("nice_to_have_missing", [])
        if soft:
            lines.append(f"Nice-to-have missing: " + ", ".join(soft[:5]))

        warnings = scan.get("format_warnings", [])
        if warnings:
            lines.append("\nFormat Warnings:")
            lines += [f"  ⚠ {w}" for w in warnings]

        fixes = scan.get("quick_fixes", [])
        if fixes:
            lines.append("\nQuick Fixes:")
            lines += [f"  → {f}" for f in fixes]

        return "\n".join(lines)
